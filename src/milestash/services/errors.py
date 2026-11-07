class InvalidInput(ValueError):
    """Input a person can fix; the message is safe to show them."""


class AccountNotFound(LookupError):
    """No such account, or it belongs to someone else."""
