// pm2 ecosystem for CogniWork API (docs/deploy.md §6.4 / §5).
// Install to /etc/cogniwork/ecosystem.config.cjs (prepare-host.sh does this).
// Do not put secrets here — /opt/cogniwork/bin/api.sh sources /etc/cogniwork/env.
module.exports = {
  apps: [{
    name: 'cogniwork-api',
    script: '/opt/cogniwork/bin/api.sh',
    interpreter: 'bash',
    cwd: '/opt/cogniwork/apps/backend',

    // Hard limit (§5): fork + single instance. cluster / instances>1 splits
    // execution threads from SSE subscribers and double-recovers interrupted tasks.
    exec_mode: 'fork',
    instances: 1,

    autorestart: true,
    max_restarts: 10,
    min_uptime: '30s',
    // SIGINT first (uvicorn graceful); then SIGKILL. Task threads are daemons —
    // hard kill drops in-flight graphs (checkpoint recovers; live SSE does not).
    kill_timeout: 60000,
    watch: false,
    error_file: '/var/log/cogniwork/api.err.log',
    out_file: '/var/log/cogniwork/api.out.log',
    time: true,
  }],
}
