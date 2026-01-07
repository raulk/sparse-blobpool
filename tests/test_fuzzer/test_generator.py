import json
from random import Random

from sparse_blobpool.config import SimulationConfig
from sparse_blobpool.fuzzer.config import ParameterRanges
from sparse_blobpool.fuzzer.generator import (
    config_to_dict,
    generate_num_transactions,
    generate_run_id,
    generate_simulation_config,
    validate_config,
)


def test_generate_run_id_returns_string() -> None:
    run_id = generate_run_id(Random(42))
    assert isinstance(run_id, str)
    assert len(run_id) > 5


def test_generate_run_id_deterministic_with_same_seed() -> None:
    run_id1 = generate_run_id(Random(42))
    run_id2 = generate_run_id(Random(42))
    assert run_id1 == run_id2


def test_generate_simulation_config_within_ranges() -> None:
    ranges = ParameterRanges()
    config = generate_simulation_config(Random(42), ranges, 60.0)

    assert ranges.node_count[0] <= config.node_count <= ranges.node_count[1]
    assert ranges.mesh_degree[0] <= config.mesh_degree <= ranges.mesh_degree[1]
    assert (
        ranges.provider_probability[0]
        <= config.provider_probability
        <= ranges.provider_probability[1]
    )
    assert config.duration == 60.0


def test_generate_num_transactions_within_range() -> None:
    for _ in range(100):
        num = generate_num_transactions(Random(), (1, 20))
        assert 1 <= num <= 20


def test_validate_config_valid() -> None:
    config = SimulationConfig(node_count=100, mesh_degree=50)
    is_valid, errors = validate_config(config)
    assert is_valid
    assert errors == []


def test_validate_config_invalid_mesh_degree() -> None:
    config = SimulationConfig(node_count=10, mesh_degree=50)
    is_valid, errors = validate_config(config)
    assert not is_valid
    assert any("mesh_degree" in e for e in errors)


def test_validate_config_invalid_custody_columns() -> None:
    config = SimulationConfig(custody_columns=200)
    is_valid, errors = validate_config(config)
    assert not is_valid
    assert any("custody_columns" in e for e in errors)


def test_validate_config_invalid_max_columns_per_request() -> None:
    config = SimulationConfig(max_columns_per_request=20, custody_columns=8)
    is_valid, errors = validate_config(config)
    assert not is_valid
    assert any("max_columns_per_request" in e for e in errors)


def test_validate_config_invalid_timeout() -> None:
    config = SimulationConfig(request_timeout=1.0, provider_observation_timeout=2.0)
    is_valid, errors = validate_config(config)
    assert not is_valid
    assert any("request_timeout" in e for e in errors)


def test_config_to_dict_is_json_serializable() -> None:
    config = SimulationConfig(node_count=100, mesh_degree=50)
    d = config_to_dict(config)
    json_str = json.dumps(d)
    assert isinstance(json_str, str)
    assert len(json_str) > 0


def test_config_to_dict_contains_required_fields() -> None:
    config = SimulationConfig(node_count=100, mesh_degree=50)
    d = config_to_dict(config)
    assert "node_count" in d
    assert "mesh_degree" in d
    assert "seed" in d
    assert "duration" in d
    assert d["node_count"] == 100
    assert d["mesh_degree"] == 50
