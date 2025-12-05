class GarakError(Exception):
    """Base exception for Garak errors"""
    pass


class GarakConfigError(GarakError):
    """Configuration related errors"""
    pass


class GarakValidationError(GarakError):
    """Validation related errors"""
    pass


class GarakScanError(GarakError):
    """Scan execution errors"""
    pass

