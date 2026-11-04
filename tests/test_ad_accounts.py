"""AD GUID bindings remain distinct from every existing OIDC account binding."""
from pathlib import Path
import tempfile
import unittest

from launchpad.accounts import (
    AccountError, assign_mentor, assigned_learner_ids, create_auth_session,
    enroll_account, get_account_for_identity, get_session_account,
    set_account_active, unassign_mentor, validate_accounts_database,
)
from launchpad.real_data import initialize_real_database
from launchpad.storage import mark_module_complete, module_is_complete


class ADAccountsTests(unittest.TestCase):
    issuer = "urn:launchpad:ad:65ad7fe1-a6d6-4317-a1ca-3a27786e228d"
    subject = "341cf45f-e18a-4f64-b1f4-47e94510b13d"
    other_subject = "7192f0c7-169c-46c0-a2de-6432d8fce250"

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(dir="/tmp")
        self.addCleanup(self.directory.cleanup)
        self.database = Path(self.directory.name) / "learners.sqlite"
        initialize_real_database(self.database)

    def enroll(self, subject=None, role="learner"):
        return enroll_account(self.issuer, subject or self.subject, "Same synthetic name", role, db_path=self.database)

    def test_stable_guid_mapping_never_claims_oidc_or_same_name_progress(self):
        oidc = enroll_account("https://identity.example.invalid", self.subject, "Same synthetic name", db_path=self.database)
        mark_module_complete(oidc["learner_id"], "hardware_basics", True, self.database)
        self.assertIsNone(get_account_for_identity(self.issuer, self.subject, self.database))
        ad = self.enroll()
        other = self.enroll(self.other_subject)
        self.assertEqual(len({oidc["learner_id"], ad["learner_id"], other["learner_id"]}), 3)
        self.assertFalse(module_is_complete(ad["learner_id"], "hardware_basics", self.database))
        self.assertEqual(get_account_for_identity(self.issuer, self.subject, self.database), ad)
        with self.assertRaises(AccountError):
            enroll_account(self.issuer, self.subject, "Changed display name", db_path=self.database)
        validate_accounts_database(self.database)

    def test_ad_namespace_and_subject_require_canonical_nonnil_uuid(self):
        invalid = ["", "name", self.subject.upper(), self.subject.replace("-", ""),
                   "{" + self.subject + "}", "00000000-0000-0000-0000-000000000000", None]
        for identifier in invalid:
            with self.subTest(identifier=identifier), self.assertRaises(AccountError):
                enroll_account(self.issuer, identifier, "Invented", db_path=self.database)
            with self.subTest(directory=identifier), self.assertRaises(AccountError):
                enroll_account("urn:launchpad:ad:" + str(identifier), self.subject, "Invented", db_path=self.database)
        for issuer in ("urn:launchpad:ad", self.issuer + ":extra", self.issuer + " ",
                       self.issuer.replace("urn:", "URN:"), "ldap://directory.example.invalid"):
            with self.subTest(issuer=issuer), self.assertRaises(AccountError):
                enroll_account(issuer, self.subject, "Invented", db_path=self.database)

    def test_ad_accounts_keep_explicit_assignments_and_existing_revocation_controls(self):
        learner = self.enroll()
        mentor = self.enroll(self.other_subject, "mentor")
        self.assertEqual(assigned_learner_ids(mentor["id"], self.database), [])
        assign_mentor(mentor["id"], learner["learner_id"], self.database)
        self.assertEqual(assigned_learner_ids(mentor["id"], self.database), [learner["learner_id"]])
        mentor_token = create_auth_session(mentor["id"], self.database)
        learner_token = create_auth_session(learner["id"], self.database)
        unassign_mentor(mentor["id"], learner["learner_id"], self.database)
        self.assertIsNone(get_session_account(mentor_token, self.database))
        self.assertIsNotNone(get_session_account(learner_token, self.database))
        set_account_active(learner["id"], False, self.database)
        self.assertIsNone(get_session_account(learner_token, self.database))


if __name__ == "__main__":
    unittest.main()
