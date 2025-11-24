# Store the version here so:
# 1) we don't load dependencies by storing it in __init__.py
# 2) we can import it in setup.py for the same reason
# 3) we can import it into your module module

# version 3.0.0 N Waterton Dec 2025 - added version number.
# version 3.0.1 N Waterton 16th Jan 2025 added async_art_remove_mats.py example, fixed art_remove_mats.py
# version 3.0.2 N Waterton 11th March 2025 - changed image compare function in async_update_from_directory.py, updated README and setup.py
# version 3.0.3 N Waterton 24th march 2025 added asyncio.Lock to '_get_device_info' in async_art.py updated web_interface to fully async.

__version__ = '3.0.3'