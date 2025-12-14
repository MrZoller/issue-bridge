# Quick Start Guide

Get IssueBridge up and running in minutes!

## Method 1: Docker (Recommended)

### Prerequisites
- Docker and Docker Compose installed on your system
- **GitLab Personal Access Tokens** for each instance you want to sync
  - Must have scopes: `api`, `read_api`, `write_repository`
  - See [Getting GitLab Access Tokens](#getting-gitlab-access-tokens) section below for step-by-step instructions

### Steps

1. **Start the service**:
   ```bash
   cd IssueBridge
   docker-compose up -d
   ```

2. **Access the web interface**:
   Open your browser to: `http://localhost:8000`

3. **Configure GitLab instances**:
   - Click on "GitLab Instances" tab
   - Add your first instance:
     - Name: `Production`
     - URL: `https://gitlab.example.com`
     - Access Token: `your-token-here`
   - Add your second instance (repeat for additional instances)

4. **Create user mappings** (optional but recommended):
   - Click on "User Mappings" tab
   - Map usernames between instances
   - Example: `john.doe` on Production → `jdoe` on Development

5. **Create a project pair**:
   - Click on "Project Pairs" tab
   - Fill in the form:
     - Name: `MyProject Sync`
     - Source Instance: `Production`
     - Source Project: `group/myproject` (or project ID like `123`)
     - Target Instance: `Development`
     - Target Project: `group/myproject`
     - Check "Bidirectional Sync" for two-way sync
     - Check "Sync Enabled" to start syncing
     - Set sync interval (default: 10 minutes)
   - Click "Add Project Pair"

6. **Monitor the sync**:
   - Go back to "Dashboard" tab
   - Watch your issues sync!
   - Check "Sync Logs" for detailed activity
   - Check "Conflicts" for any issues needing manual resolution

### Managing the Docker Service

```bash
# View logs
docker-compose logs -f

# Stop the service
docker-compose down

# Restart the service
docker-compose restart

# Update and rebuild
git pull
docker-compose up -d --build
```

## Method 2: Manual Installation

### Prerequisites
- Python 3.11 or higher
- pip
- **GitLab Personal Access Tokens** for each instance you want to sync
  - Must have scopes: `api`, `read_api`, `write_repository`
  - See [Getting GitLab Access Tokens](#getting-gitlab-access-tokens) section below for step-by-step instructions

### Steps

1. **Set up Python environment**:
   ```bash
   cd IssueBridge
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. **Run the application**:
   ```bash
   python -m app.main
   ```

3. **Access the web interface**:
   Open your browser to: `http://localhost:8000`

4. **Follow steps 3-6 from Docker method above**

## Getting GitLab Access Tokens

For each GitLab instance you want to sync, you need to create a Personal Access Token.

### Required Token Scopes

Your token must have **all three** of these scopes:
- ✅ **`api`** - Full API access
- ✅ **`read_api`** - Read API access
- ✅ **`write_repository`** - Write access for creating issues

### Step-by-Step Token Creation

**For GitLab.com or Self-Hosted GitLab:**

1. **Log into your GitLab instance**
   - GitLab.com: https://gitlab.com
   - Self-hosted: Your instance URL

2. **Navigate to Access Tokens**
   - Click your **avatar** (profile picture) in the top-right corner
   - Select **"Settings"**
   - Click **"Access Tokens"** in the left sidebar

3. **Create a new token**
   - **Token name**: `GitLab IssueBridge` (or any descriptive name)
   - **Expiration date**:
     - Production: 90 days to 1 year
     - Testing: 7-30 days
   - **Scopes** - Check **all three** boxes:
     - ☑️ `api`
     - ☑️ `read_api`
     - ☑️ `write_repository`

4. **Generate and save the token**
   - Click **"Create personal access token"**
   - ⚠️ **CRITICAL**: Copy the token **immediately**
   - You will **never see this token again** after leaving the page
   - Save it in a password manager or secure location

5. **Use the token in the application**
   - When adding a GitLab instance, paste this token in the "Access Token" field

### Security Notes

- 🔒 Never share tokens or commit them to version control
- 🔄 Set expiration dates and rotate tokens periodically
- 🗄️ The application stores tokens securely in its database
- 👥 For production, consider using a dedicated service account

## Common Use Cases

### Case 1: One-Way Sync (Production → Development)

1. Add both instances
2. Create project pair with:
   - Source: Production instance
   - Target: Development instance
   - **Uncheck** "Bidirectional Sync"
3. Issues will only sync from Production to Development

### Case 2: Two-Way Sync with User Mapping

1. Add both instances
2. Create user mappings for all team members:
   - Map each user from Instance A to Instance B
   - Also map from Instance B to Instance A (for bidirectional)
3. Create project pair with "Bidirectional Sync" enabled
4. Issues and assignees will sync both ways

### Case 3: Multiple Project Pairs

1. Add all your GitLab instances
2. Create multiple project pairs with different configurations:
   - Some bidirectional, some one-way
   - Different sync intervals for each pair
3. Each pair operates independently

## Troubleshooting

### Issues not syncing?

1. Check Dashboard - is the project pair enabled?
2. Check Sync Logs - are there any errors?
3. Verify access tokens are valid
4. Ensure project IDs/paths are correct

### Conflicts appearing?

1. Go to "Conflicts" tab
2. Review the conflicting changes
3. Manually update one of the issues in GitLab
4. Mark the conflict as resolved in the UI
5. The next sync will pick up your manual changes

### Users not being assigned?

1. Check "User Mappings" tab
2. Ensure mappings exist for those users
3. Verify usernames are correct on both instances
4. Check Sync Logs for warnings about missing mappings

## Next Steps

- Set up monitoring (check Dashboard regularly)
- Configure appropriate sync intervals
- Test with a small project first
- Read the full README.md for advanced features

## Support

If you encounter issues:
1. Check the logs: `docker-compose logs -f`
2. Review the troubleshooting section in README.md
3. Open an issue on GitHub

Enjoy your synchronized GitLab issues!
