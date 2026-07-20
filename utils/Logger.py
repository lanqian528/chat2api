import logging

from utils.log_buffer import log_buffer

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')

# 附加：把所有日志同时送进内存环形缓冲，供管理后台 UI 读取
# 不替换 stdout handler，仅增加一份内存副本
_root = logging.getLogger()
if not any(isinstance(h, type(log_buffer)) for h in _root.handlers):
    _root.addHandler(log_buffer)


class Logger:
    @staticmethod
    def info(message):
        logging.info(str(message))

    @staticmethod
    def warning(message):
        logging.warning("\033[0;33m" + str(message) + "\033[0m")

    @staticmethod
    def error(message):
        logging.error("\033[0;31m" + "-" * 50 + '\n| ' + str(message) + "\033[0m" + "\n" + "└" + "-" * 80)

    @staticmethod
    def debug(message):
        logging.debug("\033[0;37m" + str(message) + "\033[0m")


logger = Logger()
