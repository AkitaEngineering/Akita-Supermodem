"""
Stub protobuf module for testing purposes.
This allows tests to run without requiring the protoc compiler.
In production, this file should be generated from akita.proto using protoc.
"""

class FileStart:
    def __init__(self, **kwargs):
        self.filename = kwargs.get('filename', '')
        self.total_size = kwargs.get('total_size', 0)
        self.piece_size = kwargs.get('piece_size', 0)
        self.merkle_root = kwargs.get('merkle_root', None)
        self.piece_hashes = kwargs.get('piece_hashes', [])
    
    def HasField(self, field_name):
        return getattr(self, field_name, None) is not None
    
    def extend(self, items):
        """Stub for extend method used with piece_hashes."""
        if not hasattr(self, 'piece_hashes'):
            self.piece_hashes = []
        self.piece_hashes.extend(items)

class PieceData:
    def __init__(self, **kwargs):
        self.piece_index = kwargs.get('piece_index', 0)
        self.data = kwargs.get('data', b'')

class ResumeRequest:
    def __init__(self, **kwargs):
        self.missing_indices = kwargs.get('missing_indices', [])
        self.acknowledged_indices = kwargs.get('acknowledged_indices', [])

class Acknowledgement:
    def __init__(self, **kwargs):
        self.piece_index = kwargs.get('piece_index', 0)

class AkitaMessage:
    def __init__(self):
        self.file_start = FileStart()
        self.piece_data = PieceData()
        self.resume_request = ResumeRequest()
        self.acknowledgement = Acknowledgement()
    
    def HasField(self, field_name):
        obj = getattr(self, field_name, None)
        if obj is None:
            return False
        # Check if it's a default/empty object
        if hasattr(obj, 'filename') and not obj.filename:
            return False
        if hasattr(obj, 'piece_index') and obj.piece_index == 0 and not obj.data:
            return False
        if hasattr(obj, 'missing_indices') and not obj.missing_indices:
            return False
        return True
    
    def SerializeToString(self):
        # Stub - returns empty bytes for testing
        return b''
    
    def ParseFromString(self, data):
        # Stub - does nothing for testing
        pass

# Add CopyFrom method to message classes
def _copy_from_file_start(self, other):
    self.filename = other.filename
    self.total_size = other.total_size
    self.piece_size = other.piece_size
    self.merkle_root = other.merkle_root
    self.piece_hashes = list(other.piece_hashes) if hasattr(other, 'piece_hashes') else []

def _copy_from_piece_data(self, other):
    self.piece_index = other.piece_index
    self.data = other.data

def _copy_from_resume_request(self, other):
    self.missing_indices = list(other.missing_indices) if hasattr(other, 'missing_indices') else []
    self.acknowledged_indices = list(other.acknowledged_indices) if hasattr(other, 'acknowledged_indices') else []

# Monkey-patch CopyFrom methods
FileStart.CopyFrom = lambda self, other: _copy_from_file_start(self, other)
PieceData.CopyFrom = lambda self, other: _copy_from_piece_data(self, other)
ResumeRequest.CopyFrom = lambda self, other: _copy_from_resume_request(self, other)

# Add CopyFrom to AkitaMessage
def _akita_message_copy_from(self, other):
    if isinstance(other, FileStart):
        _copy_from_file_start(self.file_start, other)
    elif isinstance(other, PieceData):
        _copy_from_piece_data(self.piece_data, other)
    elif isinstance(other, ResumeRequest):
        _copy_from_resume_request(self.resume_request, other)

AkitaMessage.CopyFrom = _akita_message_copy_from

