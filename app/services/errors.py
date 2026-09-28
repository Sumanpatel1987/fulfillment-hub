class DomainError(Exception):
    """Base class for expected workflow errors."""


class NotFoundError(DomainError):
    pass


class InvalidTransitionError(DomainError):
    pass


class BlockingExceptionError(DomainError):
    pass


class WrongBarcodeError(DomainError):
    pass


class InsufficientInventoryError(DomainError):
    pass


class TransferError(DomainError):
    pass
