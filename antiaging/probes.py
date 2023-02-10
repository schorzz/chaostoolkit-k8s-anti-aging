# -*- coding: utf-8 -*-
from chaoslib.types import Configuration
from chaoslib.types import Secrets


__all__ = []


def empty_probe(configuration: Configuration = None, secrets: Secrets = None) -> bool:
    return True
