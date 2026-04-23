module.exports = {
  apps: [{
    name: 'capswriter',
    script: 'start_client.py',
    cwd: '/Users/yangqian/Downloads/local_asr/CapsWriter-Offline',
    interpreter: '/Users/yangqian/miniconda3/bin/python',
    env: {
      NO_PROXY: '192.168.0.0/16'
    },
    autorestart: true,
    max_restarts: 10,
    min_uptime: '10s',
    watch: false,
    max_memory_restart: '1G',
    log_date_format: 'YYYY-MM-DD HH:mm:ss Z',
    error_file: './logs/pm2-error.log',
    out_file: './logs/pm2-out.log',
    merge_logs: true,
    // PM2 重启时等待优雅退出
    kill_timeout: 5000,
    // 监听退出信号
    listen_timeout: 5000,
  }]
};
