from .base import Provider


class UnknownProvider(LookupError):
    pass


_providers: dict[str, Provider] = {}


def register[P: type[Provider]](cls: P) -> P:
    if cls.key in _providers:
        raise ValueError(f"Two providers use the key {cls.key!r}")
    _providers[cls.key] = cls()
    return cls


def get_provider(key: str) -> Provider:
    try:
        return _providers[key]
    except KeyError:
        raise UnknownProvider(key) from None


def all_providers() -> list[Provider]:
    return sorted(_providers.values(), key=lambda provider: provider.name)
