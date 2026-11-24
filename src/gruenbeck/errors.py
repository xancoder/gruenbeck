"""common base class of the errors of the package"""


class GruenbeckError(Exception):
    """
    an expected failure of a run (configuration, device, data files, stored values)

    Only gruenbeck.cli catches it: gruenbeck-collect logs the message, sends it as error
    mail and ends with exit code 1. The subclasses live in the modules that raise them.
    """
