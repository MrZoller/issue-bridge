# GitLab Issue Transfer Buddy - Safe Testing Guide

This guide provides step-by-step instructions for safely testing the synchronization functionality using test projects, ensuring you don't accidentally affect production data.

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Test Environment Setup](#test-environment-setup)
3. [Safety Checklist](#safety-checklist)
4. [Test Scenario Walkthrough](#test-scenario-walkthrough)
5. [Verification Steps](#verification-steps)
6. [Cleanup](#cleanup)
7. [Troubleshooting](#troubleshooting)

---

## Prerequisites

### Required Access

- **Two GitLab Instances** (choose one of these options):
  - Option A: Two separate GitLab.com accounts (recommended for isolation)
  - Option B: One GitLab.com account + one self-hosted GitLab instance
  - Option C: Two self-hosted GitLab instances
  - Option D: Two test projects on the same GitLab instance (easier but less realistic)

### Required Tools

```bash
# Install Docker (if using containerized deployment)
docker --version
docker-compose --version

# OR install Python dependencies (if running locally)
python --version  # Requires Python 3.11+
pip install -r requirements.txt
```

---

## Test Environment Setup

### Step 1: Create Test Projects on GitLab

**IMPORTANT: Use dedicated test projects, not production projects!**

#### On Source GitLab Instance:

1. Create a new project: `sync-test-source`
2. Add some test issues with:
   - Different titles and descriptions
   - Various labels (e.g., `bug`, `feature`, `test`)
   - Milestones (e.g., `v1.0 Test Milestone`)
   - Comments
   - Assignees
   - Due dates
   - Different states (open/closed)

Example test issues to create:
```
Issue #1: Test Bug Report
- Labels: bug, high-priority
- Assignee: yourself
- Description: "This is a test bug for sync testing"
- Comments: Add 2-3 comments

Issue #2: Test Feature Request
- Labels: feature
- Milestone: v1.0 Test Milestone
- Due date: 1 week from now
- Description: "This is a test feature request"

Issue #3: Closed Test Issue
- State: Closed
- Description: "This tests closed issue synchronization"
```

#### On Target GitLab Instance:

1. Create a new project: `sync-test-target`
2. Leave it empty initially (sync will populate it)
3. Pre-create matching labels and milestones (optional, but recommended to verify auto-creation):
   - Labels: `bug`, `feature`, `test`, `high-priority`
   - Milestone: `v1.0 Test Milestone`

### Step 2: Generate Access Tokens

For each GitLab instance, create a Personal Access Token with the required permissions.

#### Creating Test Tokens

**For GitLab.com or Self-Hosted GitLab:**

1. **Log into your GitLab instance**
   - GitLab.com: https://gitlab.com
   - Self-hosted: Your GitLab instance URL

2. **Navigate to Access Tokens settings**
   - Click your **avatar/profile picture** in the top-right corner
   - Select **"Settings"** from the dropdown
   - In the left sidebar, click **"Access Tokens"**

3. **Create a new test token**
   - **Token name**: `Test - Issue Sync Service` (include "Test" to identify it later)
   - **Expiration date**: 7-14 days (short-lived for testing security)
   - **Select scopes** - Check **all three** boxes:
     - ☑️ `api` (Full API access - required for creating/updating issues, labels, milestones)
     - ☑️ `read_api` (Read access - required for fetching issues and project data)
     - ☑️ `write_repository` (Write access - required for creating issues and comments)

4. **Generate the token**
   - Click **"Create personal access token"**
   - ⚠️ **IMPORTANT**: Copy the token immediately and store it securely
   - You will **not** be able to see this token again after leaving the page

5. **Store tokens securely during testing**
   - Use a password manager or secure notes app
   - Create a temporary test file (e.g., `test_tokens.txt`) but **NEVER commit it**
   - Add `test_tokens.txt` to `.gitignore` if you create one

**⚠️ SECURITY NOTES:**
- Never commit access tokens to version control
- Never share tokens in chat, email, or public forums
- Use short expiration periods for test tokens (7-14 days)
- Revoke test tokens immediately after testing is complete
- For testing, it's fine to use your personal account tokens
- For production, use a dedicated service account instead

### Step 3: Configure Test Environment

#### Option A: Using Docker (Recommended)

1. Create a test-specific environment file:

```bash
cp .env.example .env.test
```

2. Edit `.env.test`:

```ini
# Database - use separate test database
DATABASE_URL=sqlite:///./test_sync.db

# Server configuration
HOST=0.0.0.0
PORT=8000

# Sync settings - use shorter interval for testing
DEFAULT_SYNC_INTERVAL_MINUTES=2

# Logging - verbose for testing
LOG_LEVEL=DEBUG
```

3. Create test-specific docker-compose file:

```bash
cp docker-compose.yml docker-compose.test.yml
```

4. Edit `docker-compose.test.yml`:

```yaml
version: '3.8'

services:
  sync-app-test:
    build: .
    container_name: gitlab-sync-test
    ports:
      - "8001:8000"  # Different port to avoid conflicts
    volumes:
      - ./test_data:/data  # Separate volume for test data
    env_file:
      - .env.test
    restart: unless-stopped
```

5. Start the test application:

```bash
docker-compose -f docker-compose.test.yml up -d
```

#### Option B: Running Locally

1. Create virtual environment:

```bash
python -m venv venv-test
source venv-test/bin/activate  # On Windows: venv-test\Scripts\activate
```

2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Set environment variables:

```bash
export DATABASE_URL="sqlite:///./test_sync.db"
export HOST="0.0.0.0"
export PORT="8001"
export DEFAULT_SYNC_INTERVAL_MINUTES="2"
export LOG_LEVEL="DEBUG"
```

4. Run the application:

```bash
python -m app.main
```

### Step 4: Access the Dashboard

Open your browser to:
- Docker: http://localhost:8001
- Local: http://localhost:8001

You should see the GitLab Issue Transfer Buddy dashboard.

---

## Safety Checklist

Before proceeding with tests, verify:

- [ ] Using dedicated test projects (NOT production projects)
- [ ] Using test-specific database file (`test_sync.db`)
- [ ] Access tokens are for test accounts/projects only
- [ ] Application running on different port (8001) if production instance exists
- [ ] Separate Docker volume (`test_data`) if using containers
- [ ] Short token expiration (7 days max)
- [ ] Team members notified if using shared test projects
- [ ] Backup of any important test data (if applicable)

---

## Test Scenario Walkthrough

### Test 1: Basic Unidirectional Sync (Source → Target)

#### Step 1: Configure GitLab Instances

1. Navigate to **Instances** page
2. Click **"Add Instance"**
3. Add source instance:
   - Name: `Test Source`
   - URL: `https://gitlab.com` (or your instance URL)
   - Access Token: [paste your source token]
4. Click **"Add Instance"** again for target:
   - Name: `Test Target`
   - URL: `https://gitlab.com` (or your target instance URL)
   - Access Token: [paste your target token]
5. Verify both instances show as "Active"

#### Step 2: Create User Mappings (Optional but Recommended)

1. Navigate to **User Mappings** page
2. Click **"Add Mapping"**
3. Map your usernames:
   - Source Instance: `Test Source`
   - Source Username: [your username on source instance]
   - Target Instance: `Test Target`
   - Target Username: [your username on target instance]
4. Add mappings for any other users who are assignees

**Note:** If you skip this, issues will sync without assignee mappings.

#### Step 3: Create Project Pair

1. Navigate to **Project Pairs** page
2. Click **"Add Project Pair"**
3. Configure:
   - Name: `Test Sync Pair - Unidirectional`
   - Source Instance: `Test Source`
   - Source Project ID: [find your `sync-test-source` project ID]*
   - Target Instance: `Test Target`
   - Target Project ID: [find your `sync-test-target` project ID]*
   - Bidirectional: ❌ **Unchecked** (unidirectional for first test)
   - Sync Interval: `2` minutes
   - Enabled: ✅ **Checked**
4. Click **"Create"**

*How to find Project ID: Go to project in GitLab → Settings → General → Project ID is shown at the top

#### Step 4: Trigger Manual Sync

1. In **Project Pairs** page, find your test pair
2. Click **"Sync Now"** button
3. Monitor the dashboard for activity

#### Step 5: Verify Sync Results

##### On the Dashboard:

1. Navigate to **Dashboard** page
2. Check **Statistics**:
   - Total synced issues should increment
   - Recent activity should show sync logs
3. Navigate to **Sync Logs** page
4. Verify entries show:
   - Direction: `SOURCE_TO_TARGET`
   - Status: `SUCCESS`
   - Messages indicating created/updated issues

##### On Target GitLab Project:

1. Open your `sync-test-target` project in GitLab
2. Go to **Issues** tab
3. Verify all source issues are present with:
   - ✅ Correct titles and descriptions
   - ✅ Labels created and applied
   - ✅ Milestones created and assigned
   - ✅ Comments synced with attribution
   - ✅ Due dates preserved
   - ✅ States (open/closed) matched
   - ✅ Assignees mapped (if user mappings configured)
   - ✅ Description includes link to source issue

##### On Synced Issues Page:

1. Navigate to **Synced Issues** page
2. Verify mappings show:
   - Source issue IIDs
   - Target issue IIDs
   - Last synced timestamps

---

### Test 2: Update Detection and Sync

This test verifies that changes on the source are detected and synced.

#### Step 1: Modify Source Issue

1. Go to source project (`sync-test-source`)
2. Open Issue #1
3. Make changes:
   - Update title: Add `[MODIFIED]` prefix
   - Edit description: Add new paragraph
   - Add new label: `modified`
   - Add new comment: "This is a test comment after initial sync"

#### Step 2: Wait for Automatic Sync

- Wait for the next scheduled sync (up to 2 minutes)
- Or click **"Sync Now"** to trigger immediately

#### Step 3: Verify Updates Propagated

1. Go to target project (`sync-test-target`)
2. Find the corresponding issue
3. Verify changes:
   - ✅ Title updated with `[MODIFIED]` prefix
   - ✅ Description includes new paragraph
   - ✅ New label `modified` applied
   - ✅ New comment appears with attribution
4. Check **Sync Logs**:
   - Should show `updated` operation
   - Action: "Updated issue from source"

---

### Test 3: Conflict Detection

This test verifies the system detects concurrent modifications.

#### Step 1: Modify Both Source and Target

1. **On source project**:
   - Open Issue #2
   - Change title to: "Source Modified Title"
   - Add comment: "Modified on source"

2. **On target project**:
   - Find corresponding Issue #2
   - Change title to: "Target Modified Title"
   - Add comment: "Modified on target"

#### Step 2: Trigger Sync

- Click **"Sync Now"** on the project pair

#### Step 3: Verify Conflict Detection

1. Navigate to **Conflicts** page
2. Verify a conflict entry appears showing:
   - ✅ Source and target issue IIDs
   - ✅ Conflict detected timestamp
   - ✅ Source snapshot (JSON with source state)
   - ✅ Target snapshot (JSON with target state)
   - ✅ Status: Unresolved

3. Check **Sync Logs**:
   - Status should be `CONFLICT`
   - Message indicates concurrent modification detected

#### Step 4: Resolve Conflict

1. Manually decide which version to keep (source or target)
2. In GitLab, update the issue to the desired final state
3. In the application, navigate to **Conflicts** page
4. Click **"Mark Resolved"** for the conflict
5. Add resolution notes explaining your decision

---

### Test 4: Bidirectional Sync

This test enables two-way synchronization.

#### Step 1: Update Project Pair Configuration

1. Navigate to **Project Pairs** page
2. Click **"Edit"** on your test pair
3. Change settings:
   - Bidirectional: ✅ **Checked**
4. Save changes

#### Step 2: Create Issue on Target

1. Go to target project (`sync-test-target`)
2. Create a new issue:
   - Title: "Created on Target"
   - Description: "This issue originated on the target instance"
   - Label: `target-created`

#### Step 3: Wait for Sync

- Wait up to 2 minutes for scheduled sync
- Or click **"Sync Now"**

#### Step 4: Verify Reverse Sync

1. Check **Sync Logs**:
   - Should see entry with direction: `TARGET_TO_SOURCE`
2. Go to source project (`sync-test-source`)
3. Verify new issue appears with:
   - ✅ Title: "Created on Target"
   - ✅ Description includes link back to target issue
   - ✅ Label: `target-created`

---

### Test 5: Comment Synchronization

This test verifies comment handling and deduplication.

#### Step 1: Add Multiple Comments on Source

1. Go to source issue
2. Add 3 comments with different content
3. Wait for sync or trigger manually

#### Step 2: Verify Comments on Target

1. Open corresponding target issue
2. Verify all 3 comments appear with:
   - ✅ Correct content
   - ✅ Author attribution (e.g., "Comment by @username")
   - ✅ Preserved order

#### Step 3: Test Deduplication

1. Trigger sync again (manually or wait for schedule)
2. Verify comments are NOT duplicated on target
3. Check **Sync Logs**:
   - Should show "No new comments to sync" or similar message

---

### Test 6: Label and Milestone Auto-Creation

This test verifies automatic creation of missing labels/milestones.

#### Step 1: Create New Label on Source

1. Go to source project
2. Create new label:
   - Name: `auto-created-label`
   - Color: `#FF0000`
3. Apply to an existing issue

#### Step 2: Create New Milestone on Source

1. Create milestone:
   - Title: `Auto-Test Milestone`
   - Due date: 2 weeks from now
2. Assign to an existing issue

#### Step 3: Sync and Verify

1. Trigger sync
2. On target project, verify:
   - ✅ Label `auto-created-label` exists with same color
   - ✅ Milestone `Auto-Test Milestone` exists with same due date
   - ✅ Issue has both label and milestone applied

---

### Test 7: State Synchronization (Open/Closed)

This test verifies issue state changes sync correctly.

#### Step 1: Close an Open Issue on Source

1. Find an open issue on source
2. Close the issue
3. Add a comment: "Closing this issue"

#### Step 2: Sync and Verify

1. Trigger sync
2. On target, verify:
   - ✅ Issue is now closed
   - ✅ Close comment is synced

#### Step 3: Reopen on Target (if bidirectional)

1. On target, reopen the issue
2. Trigger sync
3. On source, verify issue reopens

---

## Verification Steps

After completing tests, verify the following:

### Application Health

```bash
# Check application logs
docker-compose -f docker-compose.test.yml logs -f sync-app-test

# OR if running locally
tail -f logs/app.log  # (if logs are written to file)
```

Look for:
- ✅ No unhandled exceptions
- ✅ Successful API calls to GitLab
- ✅ Database operations completing
- ✅ Scheduler jobs executing on schedule

### Database Integrity

```bash
# Connect to test database
sqlite3 test_sync.db

# Check synced issues
SELECT COUNT(*) FROM synced_issues;

# Check sync logs
SELECT status, COUNT(*) FROM sync_logs GROUP BY status;

# Check conflicts
SELECT COUNT(*) FROM conflicts WHERE resolved = 0;

# Exit
.quit
```

Expected results:
- Synced issues count matches number of synchronized issues
- Sync logs show mix of SUCCESS and possibly some CONFLICT statuses
- Unresolved conflicts count matches what you see in UI

### API Endpoints

Test API endpoints directly:

```bash
# Get dashboard stats
curl http://localhost:8001/api/dashboard/stats

# Get sync logs
curl http://localhost:8001/api/sync/logs

# Get conflicts
curl http://localhost:8001/api/sync/conflicts

# Get synced issues
curl http://localhost:8001/api/sync/synced-issues
```

All should return valid JSON responses.

---

## Cleanup

After testing is complete, clean up test resources:

### Step 1: Stop the Application

```bash
# Docker
docker-compose -f docker-compose.test.yml down

# Local
Ctrl+C (then deactivate virtual environment)
```

### Step 2: Remove Test Data

```bash
# Remove test database
rm test_sync.db

# Remove Docker volume (if used)
rm -rf test_data/

# Remove environment file
rm .env.test
```

### Step 3: Clean Up GitLab Resources

#### Optional: Delete Test Projects

If you want to completely remove test projects:
1. Go to each test project in GitLab
2. Settings → General → Advanced → Delete project
3. Confirm deletion

#### Revoke Access Tokens

For security, revoke the test access tokens:
1. Go to GitLab → Settings → Access Tokens
2. Find your test tokens
3. Click **"Revoke"** for each

#### Optional: Keep Test Projects for Future Testing

If you want to reuse test projects:
- Delete all synced issues from target project
- Keep source issues for future test runs
- Archive projects to indicate they're for testing only

---

## Troubleshooting

### Sync Not Running

**Symptoms:** No sync activity in logs, issues not syncing

**Possible causes:**
1. Project pair not enabled
   - **Fix:** Check "Enabled" status in Project Pairs page
2. Scheduler not started
   - **Fix:** Restart application, check logs for scheduler startup
3. Invalid credentials
   - **Fix:** Verify access tokens are valid and have correct scopes

**Verification:**
```bash
# Check scheduler status in logs
docker-compose -f docker-compose.test.yml logs | grep -i scheduler

# Manual sync test
curl -X POST http://localhost:8001/api/sync/{pair_id}/trigger
```

### Issues Not Syncing Correctly

**Symptoms:** Issues missing fields, incorrect data, partial sync

**Possible causes:**
1. Missing permissions on GitLab token
   - **Fix:** Regenerate token with `api`, `read_api`, `write_repository` scopes
2. User mappings not configured
   - **Fix:** Add user mappings for all assignees
3. API rate limiting
   - **Fix:** Increase sync interval, check GitLab rate limit headers

**Verification:**
- Check sync logs for specific error messages
- Manually test GitLab API access:
  ```bash
  curl -H "PRIVATE-TOKEN: your-token" \
    "https://gitlab.com/api/v4/projects/{project_id}/issues"
  ```

### Conflicts Not Detected

**Symptoms:** Concurrent modifications not flagged as conflicts

**Possible causes:**
1. Modifications too far apart in time
   - Conflict detection compares `updated_at` timestamps
   - If source synced before target was modified, no conflict detected
2. Hash not changing
   - Only title/description changes trigger conflict detection
   - Comments alone don't cause conflicts

**Verification:**
- Make simultaneous changes to both source and target
- Trigger sync immediately after both modifications
- Check `updated_at` timestamps in sync logs

### Database Errors

**Symptoms:** Application crashes, constraint violations, locked database

**Possible causes:**
1. SQLite lock contention
   - **Fix:** Use PostgreSQL for production testing
2. Missing migrations
   - **Fix:** Delete test DB and restart (migrations run automatically)
3. Corrupt database
   - **Fix:** Delete `test_sync.db` and restart application

**Verification:**
```bash
# Check database integrity
sqlite3 test_sync.db "PRAGMA integrity_check;"

# Check schema
sqlite3 test_sync.db ".schema"
```

### API Connection Errors

**Symptoms:** "Connection refused", "Timeout", 404/401 errors

**Possible causes:**
1. Incorrect GitLab URL
   - **Fix:** Verify URL format (include `https://`, no trailing slash)
2. Network/firewall issues
   - **Fix:** Test connectivity: `curl https://gitlab.com/api/v4/version`
3. Invalid project IDs
   - **Fix:** Double-check project IDs in GitLab UI

**Verification:**
```bash
# Test instance connectivity
curl -H "PRIVATE-TOKEN: your-token" \
  "https://gitlab.com/api/v4/user"

# Test project access
curl -H "PRIVATE-TOKEN: your-token" \
  "https://gitlab.com/api/v4/projects/{project_id}"
```

---

## Testing Best Practices

### Do's ✅

- **Always use dedicated test projects** separate from production
- **Start with unidirectional sync** before testing bidirectional
- **Test one scenario at a time** and verify results before proceeding
- **Monitor sync logs** actively during testing
- **Keep sync intervals short** (2-5 minutes) during testing for faster iteration
- **Document unexpected behavior** and create issues in the repository
- **Back up test data** if it contains important information
- **Use descriptive names** for test issues/labels/milestones
- **Test error scenarios** (invalid tokens, missing projects, network errors)

### Don'ts ❌

- **Never test with production projects** unless you're absolutely certain
- **Don't enable bidirectional sync** on production data as first test
- **Don't use very short sync intervals** (< 1 minute) to avoid rate limiting
- **Don't ignore conflicts** - they indicate real synchronization issues
- **Don't commit access tokens** to version control
- **Don't skip user mappings** - test with realistic user scenarios
- **Don't test during peak hours** on shared GitLab instances
- **Don't delete conflicts** without understanding root cause

---

## Next Steps

After successful testing:

1. **Review Sync Logs** - Analyze patterns and identify any issues
2. **Document Findings** - Note any bugs, unexpected behavior, or improvements
3. **Adjust Configuration** - Fine-tune sync intervals based on your needs
4. **Plan Production Deployment** - Use insights from testing to plan rollout
5. **Consider PostgreSQL** - For production, migrate from SQLite
6. **Set Up Monitoring** - Add alerting for sync failures in production
7. **Create Runbooks** - Document operational procedures for your team

---

## Support and Feedback

If you encounter issues during testing:

1. Check the [README.md](README.md) for additional documentation
2. Review application logs for error details
3. Consult the [TROUBLESHOOTING](#troubleshooting) section above
4. Create an issue in the GitHub repository with:
   - Test scenario description
   - Expected vs. actual behavior
   - Relevant log excerpts
   - Configuration details (sanitized of tokens)

Happy testing! 🚀
