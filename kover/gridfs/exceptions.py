"""Exceptions for GridFS operations."""


class GridFSFileNotFound(Exception):
    """Exception raised when a GridFS file is not found."""


class IncorrectGridFSData(Exception):
    """Exception raised when incorrect data is passed to GridFS methods."""
