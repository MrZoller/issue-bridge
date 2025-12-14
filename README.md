# GitLab Issue Transfer Buddy

A comprehensive service for synchronizing GitLab issues between different GitLab instances. This tool is perfect for organizations that maintain mirrors of their repositories across multiple GitLab instances and need to keep issues in sync.

## Features

- **Bi-directional Synchronization**: Sync issues in both directions or configure one-way sync per project pair
- **Multiple Project Pairs**: Configure and manage multiple project pairs simultaneously
- **User Mapping**: Map usernames between different GitLab instances
- **Comprehensive Field Sync**: Syncs title, description, labels, status, comments, assignees, milestones, and due dates
- **Conflict Detection**: Automatically detects and logs conflicts for manual resolution
- **Web Interface**: Easy-to-use web dashboard for configuration and monitoring
- **Automated Scheduling**: Configurable sync intervals with background scheduler
- **Docker Support**: Run as a containerized service
- **Detailed Logging**: Complete audit trail of all sync operations
- **Issue Linking**: Adds cross-references between synced issues

## Architecture

### Technology Stack

- **Backend**: Python with FastAPI
- **Database**: SQLite (easily upgradeable to PostgreSQL)
- **GitLab API**: python-gitlab library
- **Scheduler**: APScheduler for periodic sync jobs
- **Frontend**: Vanilla JavaScript with modern CSS

### Database Schema

- **GitLab Instances**: Store connection details for GitLab instances
- **Project Pairs**: Configure which projects to sync
- **User Mappings**: Map usernames between instances
- **Synced Issues**: Track issue relationships
- **Sync Logs**: Detailed operation logs
- **Conflicts**: Log conflicts for manual resolution

## Quick Start with Docker

### Prerequisites

- Docker and Docker Compose installed
- GitLab personal access tokens with API access for each instance

### Installation

1. **Clone the repository**:
   ```bash
   git clone <repository-url>
   cd GitLabIssueTransferBuddy
   ```

2. **Start the service**:
   ```bash
   docker-compose up -d
   ```

3. **Access the web interface**:
   Open your browser to `http://localhost:8000`

4. **Configure your setup**:
   - Add GitLab instances with their URLs and access tokens
   - Create project pairs to define what to sync
   - Add user mappings to map usernames between instances
   - Enable sync and watch it work!

### Docker Commands

```bash
# Start the service
docker-compose up -d

# View logs
docker-compose logs -f

# Stop the service
docker-compose down

# Rebuild after changes
docker-compose up -d --build

# Access the database
docker-compose exec gitlab-sync sqlite3 /data/gitlab_sync.db
```

## Manual Installation (Without Docker)

### Prerequisites

- Python 3.11 or higher
- pip

### Steps

1. **Clone the repository**:
   ```bash
   git clone <repository-url>
   cd GitLabIssueTransferBuddy
   ```

2. **Create virtual environment**:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment** (optional):
   ```bash
   cp .env.example .env
   # Edit .env with your settings
   ```

5. **Run the application**:
   ```bash
   python -m app.main
   ```

6. **Access the web interface**:
   Open your browser to `http://localhost:8000`

## Configuration

### Environment Variables

Create a `.env` file or set these environment variables:

```env
# Database Configuration
DATABASE_URL=sqlite:///./gitlab_sync.db

# Server Configuration
HOST=0.0.0.0
PORT=8000

# Sync Configuration
DEFAULT_SYNC_INTERVAL_MINUTES=10

# Logging
LOG_LEVEL=INFO
```

### GitLab Access Tokens

For each GitLab instance, you need a personal access token with the following scopes:
- `api` - Full API access
- `read_api` - Read API access
- `write_repository` - Write access (for creating issues)

To create a personal access token:
1. Go to your GitLab instance
2. Navigate to User Settings > Access Tokens
3. Create a new token with the required scopes
4. Copy the token (you won't see it again!)

## Usage Guide

### 1. Add GitLab Instances

Navigate to the "GitLab Instances" tab and add your GitLab instances:

- **Name**: A friendly name (e.g., "Production", "Development")
- **URL**: The GitLab instance URL (e.g., `https://gitlab.com`)
- **Access Token**: Your personal access token
- **Description**: Optional description

### 2. Configure User Mappings

Navigate to the "User Mappings" tab to map usernames:

- **Source Instance**: The source GitLab instance
- **Source Username**: Username on the source instance
- **Target Instance**: The target GitLab instance
- **Target Username**: Username on the target instance

**Note**: Users without mappings will not be assigned to synced issues.

### 3. Create Project Pairs

Navigate to the "Project Pairs" tab and create sync configurations:

- **Name**: A descriptive name for this pair
- **Source Instance**: The source GitLab instance
- **Source Project ID/Path**: Project ID (e.g., `123`) or path (e.g., `group/project`)
- **Target Instance**: The target GitLab instance
- **Target Project ID/Path**: Project ID or path on target
- **Bidirectional Sync**: Enable for two-way sync
- **Sync Enabled**: Start syncing immediately
- **Sync Interval**: How often to sync (in minutes)

### 4. Monitor Synchronization

The **Dashboard** tab provides:
- Overall statistics (project pairs, synced issues, conflicts)
- Per-project status and last sync time
- Recent activity log
- Manual sync triggers

### 5. Handle Conflicts

Navigate to the "Conflicts" tab to view and resolve conflicts:
- Conflicts occur when the same issue is modified on both instances between syncs
- Review the conflict details
- Manually resolve the conflict in GitLab
- Mark the conflict as resolved in the UI

## How Synchronization Works

### Sync Process

1. **Fetch Issues**: Retrieve all issues from source project
2. **Check Sync Status**: Look up existing sync records
3. **Detect Changes**: Compare update timestamps
4. **Conflict Detection**: Check for concurrent updates
5. **Apply Changes**: Create or update issues on target
6. **Sync Comments**: Transfer comments with author attribution
7. **Update Records**: Store sync metadata
8. **Log Operations**: Record all actions

### Conflict Detection

Conflicts are detected when:
- An issue is modified on both instances since the last sync
- Manual resolution is required to prevent data loss

### Issue Linking

Synced issues include a reference in their description:
```
---
Synced from: https://gitlab.example.com/-/issues/123
```

## API Documentation

Once the service is running, visit:
- **Swagger UI**: `http://localhost:8000/docs`
- **ReDoc**: `http://localhost:8000/redoc`

### Key Endpoints

- `GET /api/dashboard/stats` - Dashboard statistics
- `GET /api/instances/` - List GitLab instances
- `POST /api/instances/` - Create GitLab instance
- `GET /api/project-pairs/` - List project pairs
- `POST /api/project-pairs/` - Create project pair
- `POST /api/sync/{pair_id}/trigger` - Manually trigger sync
- `GET /api/sync/logs` - Get sync logs
- `GET /api/sync/conflicts` - List conflicts

## Database

### SQLite (Default)

By default, the application uses SQLite stored at `./gitlab_sync.db` (or `/data/gitlab_sync.db` in Docker).

### PostgreSQL (Production)

For production use with PostgreSQL, update the `DATABASE_URL`:

```env
DATABASE_URL=postgresql://user:password@localhost/gitlab_sync
```

And add `psycopg2-binary` to your requirements.

## Troubleshooting

### Common Issues

**Issue: Sync not running automatically**
- Check that the project pair is enabled
- Verify the scheduler is running (check logs)
- Ensure sync interval is set correctly

**Issue: Users not assigned to issues**
- Verify user mappings exist for the users
- Check that mapped usernames exist on target instance
- Review logs for user mapping warnings

**Issue: Labels not syncing**
- Labels are automatically created on the target project
- Check GitLab API token has sufficient permissions

**Issue: Cannot connect to GitLab instance**
- Verify the URL is correct and accessible
- Check that the access token is valid
- Ensure the token has the required scopes

### Logs

View application logs:

```bash
# Docker
docker-compose logs -f gitlab-sync

# Manual installation
# Logs are printed to stdout
```

## Development

### Project Structure

```
GitLabIssueTransferBuddy/
├── app/
│   ├── api/              # API endpoints
│   ├── models/           # Database models
│   ├── services/         # Business logic
│   ├── static/           # CSS and JavaScript
│   ├── templates/        # HTML templates
│   ├── config.py         # Configuration
│   ├── main.py           # FastAPI application
│   └── scheduler.py      # Background scheduler
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── README.md
```

### Running Tests

Tests can be added in a `tests/` directory using pytest:

```bash
pip install pytest pytest-asyncio
pytest
```

### Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests
5. Submit a pull request

## Security Considerations

- **Access Tokens**: Store securely and never commit to version control
- **HTTPS**: Always use HTTPS for GitLab instances
- **Network**: Consider running in a private network
- **Database**: Protect the database file (contains access tokens)
- **Permissions**: Use least-privilege access tokens

## Limitations

- **Attachments**: File attachments are not currently synced
- **Merge Requests**: MRs are not synced (as specified in requirements)
- **Webhooks**: Uses polling instead of webhooks (simpler deployment)
- **Rate Limiting**: Respects GitLab API rate limits but doesn't implement advanced retry logic

## Future Enhancements

Possible future improvements:
- PostgreSQL support with migrations
- Webhook support for real-time sync
- Attachment synchronization
- Advanced conflict resolution strategies
- Multi-instance sync (more than 2 instances)
- Selective field sync
- Issue filtering (by label, milestone, etc.)

## License

[Add your license here]

## Support

For issues, questions, or contributions, please use the GitHub issue tracker.

## Acknowledgments

Built with:
- [FastAPI](https://fastapi.tiangolo.com/)
- [python-gitlab](https://python-gitlab.readthedocs.io/)
- [SQLAlchemy](https://www.sqlalchemy.org/)
- [APScheduler](https://apscheduler.readthedocs.io/)