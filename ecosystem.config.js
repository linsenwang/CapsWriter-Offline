module.exports = {
  apps: [
    {
      name: 'capswriter-server',
      script: './core_server.py',
      interpreter: './.venv-qwen3/bin/python',
      cwd: __dirname,
      instances: 1,
      autorestart: true,
      max_restarts: 10,
      min_uptime: '10s',
      watch: false,
      max_memory_restart: '4G',
      env: {
        PYTHONUNBUFFERED: '1'
      },
      log_date_format: 'YYYY-MM-DD HH:mm:ss Z',
      error_file: './logs/pm2-error.log',
      out_file: './logs/pm2-out.log',
      merge_logs: true,
      kill_timeout: 10000,
      listen_timeout: 10000
    }
  ]
};
