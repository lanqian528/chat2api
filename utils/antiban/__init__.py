"""Antiban: chat2api 风控规避与账号保护层（骨架）。

模块分工：
  bucket       IP-账号终身粘性桶
  cooldown     账号级冷却与请求节奏
  geo          代理 IP → 地域/时区/语言
  fingerprint  指纹扩展与持久化
  circuit      熔断与黑名单自愈
  guard        统一对外入口

总开关：ENABLE_ANTIBAN（默认 False）。未启用时本模块不影响任何现有流程。
"""

from utils.antiban.guard import acquire_context, report_error, report_network_error, report_success, init, sniff_account_warning  # noqa: F401
