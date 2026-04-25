"""Libbie — CADEN's memory layer.

Single sqlite database with the sqlite-vec extension providing vector search.
Libbie owns every write and every read of memory. She is the only module
that touches the DB.
"""
