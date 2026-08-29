import pytest
from mslt.types import SemanticType, SemanticTypeError, require_kind

def test_kind_error_is_explicit():
    t=SemanticType('DeathCount')
    with pytest.raises(SemanticTypeError):
        require_kind(t,'Exposure','partition_exposure')
