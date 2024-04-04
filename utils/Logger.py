import logging


class Logger:
    logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')

    @staticmethod
    def info(message):
        logging.info("\033[0;32m" + str(message) + "\033[0m")

    @staticmethod
    def warning(message):
        logging.warning("\033[0;33m" + str(message) + "\033[0m")

    @staticmethod
    def error(message):
        logging.error("\033[0;31m" + "-" * 120 + '\n| ' + str(message) + "\033[0m" + "\n" + "└" + "-" * 150)

    @staticmethod
    def debug(message):
        logging.debug("\033[0;37m" + str(message) + "\033[0m")
