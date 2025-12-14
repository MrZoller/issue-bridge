import os
import subprocess
import sys
import unittest


class GitLabSandboxE2ETests(unittest.TestCase):
    def test_e2e_sandbox_runner(self):
        """
        Opt-in E2E test that provisions temporary GitLab projects and runs a real sync.

        This is skipped unless you explicitly enable it, so normal CI/unit runs stay fast + safe.
        """
        if os.getenv("ISSUEBRIDGE_E2E") not in {"1", "true", "TRUE", "yes", "YES"}:
            self.skipTest("Set ISSUEBRIDGE_E2E=1 to enable GitLab E2E sandbox test")

        if not os.getenv("E2E_GITLAB_TOKEN"):
            self.skipTest("Missing E2E_GITLAB_TOKEN")

        if not (os.getenv("E2E_NAMESPACE_ID") or os.getenv("E2E_NAMESPACE_PATH")):
            self.skipTest("Missing E2E_NAMESPACE_ID or E2E_NAMESPACE_PATH")

        cmd = [sys.executable, os.path.join("scripts", "e2e_sandbox.py")]
        proc = subprocess.run(  # noqa: S603,S607 (intentional controlled subprocess)
            cmd,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=os.environ.copy(),
        )
        if proc.returncode != 0:
            self.fail(f"E2E sandbox runner failed (rc={proc.returncode}):\n{proc.stdout}")


if __name__ == "__main__":
    unittest.main()
