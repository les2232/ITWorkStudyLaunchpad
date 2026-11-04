#!/usr/bin/env bash
# Authorized operator step only. Review, then run with sudo in a private terminal.
# Start the existing controlled-test launcher as lesliec in another terminal first.
# Never run that application as root. This script does not initialize/enroll data,
# contact AD, collect passwords, start the application, or delete the older app.
set -Eeuo pipefail
umask 077
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
export LC_ALL=C

readonly REPO=/opt/project/ITWorkStudyLaunchpad
readonly RUN="$REPO/work/controlled-work-study/work-study-01"
readonly CERTS=/opt/project/certs
readonly OLD=/etc/nginx/sites-available/cca-it-support-assistant
readonly SITE=/etc/nginx/sites-available/launchpad-controlled
readonly CLOSED=/etc/nginx/sites-available/launchpad-controlled-maintenance
readonly ENABLED=/etc/nginx/sites-enabled/launchpad-controlled
readonly TRUST=/etc/nginx/launchpad-controlled
readonly HOST=lesliec.ccaurora.edu
readonly OTHER=itsupport.ccaurora.edu
readonly VM_IP=10.117.1.127
archive=''
route_mutated=0
route_enabled=0
old_mode=''

die() { printf 'STOP: %s\n' "$*" >&2; return 1; }

https_status() {
    local hostname=$1 path=$2
    curl --disable --noproxy '*' --proto '=https' --tlsv1.2 \
        --cacert /etc/ssl/certs/ca-certificates.crt \
        --resolve "$hostname:443:$VM_IP" --connect-timeout 5 --max-time 15 \
        --silent --show-error --output /dev/null --write-out '%{http_code}' \
        "https://$hostname$path"
}

expect_status() {
    local hostname=$1 path=$2 expected=$3 status attempt
    # Anonymous GETs only. Never retry a sign-in or other credentialed request.
    for attempt in 1 2 3; do
        status=$(https_status "$hostname" "$path") || return 1
        [[ "$status" == "$expected" ]] && return 0
        [[ "$attempt" == 3 ]] || sleep 1
    done
    return 1
}

nginx_check() {
    local evidence=$1
    nginx -t >"$evidence" 2>&1 || return 1
    # A conflicting name can be ignored by nginx despite a zero exit status.
    ! grep -Eiq '\[(warn|emerg|alert|crit|error)\]|conflicting server name|duplicate' "$evidence"
}

failure() {
    local status=$1 line=$2
    trap - ERR INT TERM
    set +e
    printf 'Activation stopped at script line %s (status %s). No permission reversal.\n' "$line" "$status" >&2
    if [[ "$route_enabled" == 1 ]]; then
        # Close only Launchpad; retain its enrollment, namespace and progress.
        if install -o root -g root -m 0644 "$CLOSED" "$SITE" &&
           nginx_check "$archive/nginx-maintenance.txt" &&
           systemctl reload nginx &&
           expect_status "$HOST" / 503; then
            printf 'Rollback verified: trusted HTTPS maintenance response 503.\n' >&2
        else
            printf 'URGENT: maintenance rollback could not be verified. Operator must inspect protected evidence and close access; do not reopen key permissions or restart the old app.\n' >&2
        fi
    elif [[ "$route_mutated" == 1 ]]; then
        # No candidate reload has happened. Restore only the archived old route.
        if install -o root -g root -m "$old_mode" "$archive/cca-it-support-assistant" "$OLD"; then
            if [[ -L "$ENABLED" && "$(readlink "$ENABLED")" == "$SITE" ]]; then
                unlink "$ENABLED"
            fi
            nginx_check "$archive/nginx-restored-before-reload.txt" || \
                printf 'Restored configuration needs operator review; no reload attempted.\n' >&2
        else
            printf 'URGENT: restoring the original route failed; no reload attempted.\n' >&2
        fi
    fi
    [[ -z "$archive" ]] || printf 'Restricted evidence: %s\n' "$archive" >&2
    printf 'Stop only the controlled-test launcher with Ctrl-C if this test is closed. Old application and data are retained.\n' >&2
    exit "$status"
}
trap 'failure "$?" "$LINENO"' ERR
trap 'failure 130 "$LINENO"' INT
trap 'failure 143 "$LINENO"' TERM

[[ "$EUID" == 0 ]] || die 'Run this reviewed script with sudo; it never requests a password itself.'
[[ "$#" == 0 ]] || die 'This script accepts no arguments and targets only the prepared work-study-01 run.'
for command in python3 openssl nginx curl systemctl ss patch install mktemp ps getent; do
    command -v "$command" >/dev/null || die "Required command is unavailable: $command"
done
[[ "$(readlink -f /etc/nginx/sites-enabled/cca-it-support-assistant)" == "$OLD" ]] || die 'Old enabled site differs from the reviewed configuration.'
[[ "$(stat -c '%u:%g' "$OLD")" == 0:0 ]] || die 'Old site must be root-owned.'
old_mode=$(stat -c '%a' "$OLD")
[[ "$old_mode" == 644 || "$old_mode" == 640 || "$old_mode" == 600 ]] || die 'Old site has unexpected access permissions.'
for target in "$SITE" "$CLOSED" "$ENABLED" "$TRUST"; do
    [[ ! -e "$target" && ! -L "$target" ]] || die "Existing activation path requires review: $target"
done

# Read only safe identity/process fields, never a process command or environment.
master=$(systemctl show nginx --property=MainPID --value)
[[ "$master" =~ ^[1-9][0-9]*$ ]] || die 'No running Nginx master was identified.'
[[ "$(ps -o uid= -p "$master" | tr -d ' ')" == 0 ]] || die 'Nginx master must be root to retain private-key access.'
worker_uid=$(getent passwd www-data | cut -d: -f3)
[[ "$worker_uid" =~ ^[0-9]+$ ]] || die 'The expected www-data identity is unavailable.'
workers=$(ps -o uid= --ppid "$master")
[[ -n "$workers" ]] || die 'No Nginx worker process was identified.'
while read -r worker; do
    [[ "$worker" == "$worker_uid" ]] || die 'Unexpected Nginx child identity; review consumers before changing permissions.'
done <<<"$workers"
printf 'Verified Nginx root master and www-data workers.\n'

# Restriction scope is exact. Never print any certificate/key file contents.
# Unexpected key copies/consumers require review, rather than an unsafe blanket chmod.
python3 - <<'PY'
from pathlib import Path
import os
import re
import stat
import sys

certs = Path('/opt/project/certs')
known = {certs / name for name in ('ccaurora.cer', 'fullchain.pem', 'ccaurora.key')}
def stop(message):
    print('STOP: ' + message, file=sys.stderr)
    raise SystemExit(1)
for parent in (Path('/opt'), Path('/opt/project'), certs):
    info = parent.lstat()
    if not stat.S_ISDIR(info.st_mode) or parent.resolve() != parent or info.st_uid != 0 or info.st_mode & 0o022:
        stop('Unexpected certificate parent ownership, permissions or symlink: ' + str(parent))
for path in certs.rglob('*'):
    info = path.lstat()
    if stat.S_ISDIR(info.st_mode):
        continue
    if not stat.S_ISREG(info.st_mode) or path.resolve() != path or info.st_nlink != 1:
        stop('Review nonregular/linked certificate-directory entry: ' + str(path))
    if info.st_size > 1048576:
        stop('Review unusually large certificate-directory entry: ' + str(path))
    data = path.read_bytes()
    key = bool(re.search(rb'-----BEGIN [^-\r\n]*PRIVATE KEY-----', data))
    if path in known:
        if info.st_uid != 0 or info.st_gid != 0 or not key:
            stop('Known certificate/key file has changed owner or format: ' + str(path))
    elif key or path.suffix.lower() in {'.pfx', '.p12', '.key'}:
        stop('Additional possible private-key copy needs consumer review: ' + str(path))
for path in known:
    if not path.is_file():
        stop('Missing reviewed certificate/key file: ' + str(path))
allowed = Path('/etc/nginx/sites-available/cca-it-support-assistant')
needles = (b'/opt/project/certs', b'ccaurora.key', b'ccaurora.cer', b'fullchain.pem')
seen = set()
for root in ('/etc/nginx', '/etc/systemd/system', '/usr/lib/systemd/system', '/etc/apache2', '/etc/caddy'):
    directory = Path(root)
    if not directory.exists():
        continue
    for path in directory.rglob('*'):
        if not path.is_file():
            continue
        real = path.resolve()
        if real in seen:
            continue
        seen.add(real)
        if path.stat().st_size > 1048576:
            stop('Consumer configuration requires manual review: ' + str(path))
        data = path.read_bytes()
        if any(needle in data for needle in needles) and real != allowed:
            stop('Additional certificate consumer/reference needs review: ' + str(path))
print('Reviewed certificate directory: exactly three known key-bearing files; no additional references in checked service/proxy locations.')
PY

# Match only public-key digests, kept inside this shell. No secret output or prompt.
leaf_public=$(openssl x509 -in "$CERTS/fullchain.pem" -pubkey -noout | openssl pkey -pubin -outform DER | openssl dgst -sha256)
key_public=$(openssl pkey -in "$CERTS/ccaurora.key" -passin pass: -pubout -outform DER | openssl dgst -sha256)
[[ "$leaf_public" == "$key_public" ]] || die 'Website certificate and private key do not match.'
unset leaf_public key_public
openssl verify -CAfile /etc/ssl/certs/ca-certificates.crt -no-CApath -no-CAstore -untrusted "$CERTS/fullchain.pem" \
    -purpose sslserver -verify_hostname "$HOST" "$CERTS/fullchain.pem" >/dev/null
openssl x509 -in "$CERTS/fullchain.pem" -noout -checkend 3600 >/dev/null
openssl x509 -in "$CERTS/fullchain.pem" -noout -dates -checkhost "$HOST"

archive=$(mktemp -d /var/backups/launchpad-routing.XXXXXXXXXX)
chmod 0700 "$archive"
cp -p "$OLD" "$archive/cca-it-support-assistant"
chmod 0600 "$archive/cca-it-support-assistant"
for unit in cca-it-support-assistant.service it-ai-agent.service; do
    systemctl show "$unit" --property=Id,ActiveState,SubState,User,Group,FragmentPath,DropInPaths \
        >"$archive/$unit.status.txt"
    systemctl cat "$unit" >"$archive/$unit.unit.txt"
done
stat -c '%n uid=%u gid=%g mode=%a size=%s' "$CERTS/ccaurora.cer" "$CERTS/fullchain.pem" "$CERTS/ccaurora.key" \
    >"$archive/certificate-metadata-before.txt"
printf '%s\n' 'Owner authorized current certificate use until renewal and containment on this VM.' \
    'Prior world-readable key-bearing copies establish local readability, not proof of compromise.' \
    'Permission restrictions do not erase past exposure. No key copied into this archive.' \
    >"$archive/authorization-and-exposure.txt"

# This independent containment is never undone by routing rollback.
chmod 0600 "$CERTS/ccaurora.cer" "$CERTS/fullchain.pem" "$CERTS/ccaurora.key"
python3 - <<'PY'
import os
import pwd
for name in ('lesliec', 'www-data'):
    account = pwd.getpwnam(name)
    pid = os.fork()
    if pid == 0:
        try:
            os.setgroups([])
            os.setgid(account.pw_gid)
            os.setuid(account.pw_uid)
            for filename in ('ccaurora.cer', 'fullchain.pem', 'ccaurora.key'):
                try:
                    descriptor = os.open('/opt/project/certs/' + filename, os.O_RDONLY | os.O_NOFOLLOW)
                except PermissionError:
                    continue
                os.close(descriptor)
                os._exit(1)
            os._exit(0)
        except BaseException:
            os._exit(2)
    _, status = os.waitpid(pid, 0)
    if os.waitstatus_to_exitcode(status) != 0:
        raise SystemExit('STOP: Unable to verify restricted key access for ' + name)
print('Verified lesliec and www-data cannot open any of the three shared key-bearing files.')
PY
stat -c '%n uid=%u gid=%g mode=%a size=%s' "$CERTS/ccaurora.cer" "$CERTS/fullchain.pem" "$CERTS/ccaurora.key" \
    >"$archive/certificate-metadata-after.txt"
nginx_check "$archive/nginx-after-containment.txt" || die 'Nginx configuration/key access failed validation; inspect the restricted evidence.'
printf 'Contained all three known shared key-bearing files as root:root 0600.\n'

# Preserve the other hostname and refuse an unreviewed changed baseline.
[[ "$(https_status "$OTHER" /auth/login)" == 502 ]] || die 'The itsupport baseline changed; review before routing modification.'
[[ "$(https_status "$HOST" /auth/login)" == 502 ]] || die 'The lesliec baseline changed; review before routing modification.'
printf 'Both existing hostname baselines verified as HTTPS 502.\n'

listeners=$(ss -H -ltn 'sport = :8443' | awk '{print $4}')
[[ "$listeners" == 127.0.0.1:8443 ]] || die 'Start the reviewed backend as lesliec; port 8443 must listen only on 127.0.0.1.'
# Only the public CA may be installed outside the private run. Recheck its format
# so a changed or combined PEM cannot copy a private key into Nginx's public path.
python3 - <<'PY'
from pathlib import Path
import os
import pwd
import re
import stat
root = Path('/opt/project/ITWorkStudyLaunchpad/work/controlled-work-study/work-study-01')
owner = pwd.getpwnam('lesliec').pw_uid
for path in (root.parent, root, root / 'tls'):
    info = path.lstat()
    if path.resolve() != path or not stat.S_ISDIR(info.st_mode) or info.st_uid != owner or stat.S_IMODE(info.st_mode) != 0o700:
        raise SystemExit('STOP: Controlled run/TLS directory ownership or privacy changed.')
pattern = rb'(?:\s*-----BEGIN CERTIFICATE-----\s+[A-Za-z0-9+/=\r\n]+-----END CERTIFICATE-----\s*)+'
for name in ('backend-ca.pem', 'backend.pem', 'backend.key'):
    path = root / 'tls' / name
    info = path.lstat()
    if path.resolve() != path or not stat.S_ISREG(info.st_mode) or info.st_uid != owner or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1 or info.st_size > 65536:
        raise SystemExit('STOP: Controlled backend file ownership or privacy changed.')
    if name != 'backend.key' and re.fullmatch(pattern, path.read_bytes()) is None:
        raise SystemExit('STOP: Controlled certificate must contain public certificates only.')
PY
backend_uid=$(getent passwd lesliec | cut -d: -f3)
backend_pids=$(ss -H -ltnp 'sport = :8443' | grep -oE 'pid=[0-9]+' | cut -d= -f2 | sort -u)
[[ -n "$backend_pids" ]] || die 'Could not verify the backend process owner.'
while read -r backend_pid; do
    [[ "$(ps -o uid= -p "$backend_pid" | tr -d ' ')" == "$backend_uid" ]] || die 'Backend must run as lesliec, never root.'
done <<<"$backend_pids"
openssl verify -CAfile "$RUN/tls/backend-ca.pem" -no-CApath -no-CAstore \
    -purpose sslserver -verify_hostname launchpad-controlled.invalid "$RUN/tls/backend.pem" >/dev/null
openssl x509 -in "$RUN/tls/backend.pem" -noout -checkend 3600 >/dev/null
for item in /auth/login:200 /student:401; do
    path=${item%:*}
    expected=${item##*:}
    status=$(curl --disable --noproxy '*' --proto '=https' --tlsv1.2 --cacert "$RUN/tls/backend-ca.pem" \
        --resolve launchpad-controlled.invalid:8443:127.0.0.1 -H "Host: $HOST" \
        --connect-timeout 5 --max-time 15 --silent --show-error --output /dev/null --write-out '%{http_code}' \
        "https://launchpad-controlled.invalid:8443$path")
    [[ "$status" == "$expected" ]] || die "Backend anonymous smoke check failed for $path."
done

patch --dry-run --forward -p0 -d /etc/nginx/sites-available <"$REPO/deploy/vm/retire-lesliec-route.patch" \
    >"$archive/patch-dry-run.txt" 2>&1
install -d -o root -g root -m 0755 "$TRUST"
install -o root -g root -m 0644 "$RUN/tls/backend-ca.pem" "$TRUST/backend-ca.pem"
install -o root -g root -m 0644 "$REPO/deploy/vm/launchpad-controlled.nginx.conf" "$SITE"
install -o root -g root -m 0644 "$REPO/deploy/vm/launchpad-controlled-maintenance.nginx.conf" "$CLOSED"
route_mutated=1
patch --forward -p0 -d /etc/nginx/sites-available <"$REPO/deploy/vm/retire-lesliec-route.patch" \
    >"$archive/patch-applied.txt" 2>&1
ln -s "$SITE" "$ENABLED"
route_enabled=1
nginx_check "$archive/nginx-activation.txt" || die 'Candidate Nginx configuration failed validation; selecting maintenance rollback.'
systemctl reload nginx
expect_status "$HOST" /auth/login 200 || die 'Public login check failed.'
expect_status "$HOST" /student 401 || die 'Anonymous learner access check failed.'
expect_status "$OTHER" /auth/login 502 || die 'The other hostname changed unexpectedly.'

printf '\nControlled endpoint verified: https://lesliec.ccaurora.edu/\n'
printf 'Login 200, anonymous learner access 401; itsupport retains its HTTPS 502 baseline.\n'
printf 'Restricted route/service/permission evidence: %s\n' "$archive"
printf 'No AD sign-in was attempted. Yasmin must verify her browser HTTPS and enter her own password there.\n'
printf 'Keep the supervised backend terminal open; end the test before its backend certificate expires.\n'
printf 'Rollback: install the prepared maintenance file over %s, run nginx -t, reload nginx and require HTTPS 503, then Ctrl-C the controlled backend only.\n' "$SITE"
