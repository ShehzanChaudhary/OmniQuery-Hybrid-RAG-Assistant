import logging
from datetime import timezone, timedelta, datetime

# Timezone for IST (Indian Standard Time)
ist_offset = timezone(timedelta(hours=5, minutes=30))

def setup_logger():
    """
    Sets up a logger that prints logs in a proper format with timestamps in IST.

    This function configures the logger to log messages with a custom format, suppresses warnings
    from unnecessary libraries, and sets the default log level to INFO.

    Returns:
        logger: A configured logger instance.
    """
    # Create a logger
    logger = logging.getLogger(__name__)

    # Set the default logging level to INFO
    logger.setLevel(logging.INFO)

    # Create a console handler
    console_handler = logging.StreamHandler()

    # Define the log format
    formatter = logging.Formatter(
        fmt='%(asctime)s,%(msecs)d %(name)s %(levelname)s %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # Use IST for timestamps in logs
    formatter.converter = lambda *args: datetime.now(ist_offset).timetuple()

    # Set the formatter for the console handler
    console_handler.setFormatter(formatter)

    # Add the console handler to the logger
    logger.addHandler(console_handler)

    # Suppress log messages from unnecessary libraries
    logging.getLogger("requests").setLevel(logging.WARNING)
    logging.getLogger("urllib3.connectionpool").setLevel(logging.WARNING)
    logging.getLogger("azure.core.pipeline.policies.http_logging_policy").setLevel(logging.WARNING)

    return logger

# Initialize the logger
logger = setup_logger()
