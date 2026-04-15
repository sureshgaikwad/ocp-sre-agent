# SRE Agent Tests

Comprehensive test suite for the OpenShift SRE Agent.

## Structure

```
tests/
├── unit/                          # Unit tests
│   ├── collectors/                # Collector tests
│   │   ├── test_proactive_collector.py    # Phase 4: Proactive detection tests
│   │   └── ...
│   ├── analyzers/                 # Analyzer tests
│   │   ├── test_proactive_analyzer.py     # Phase 4: Preventive diagnosis tests
│   │   └── ...
│   ├── handlers/                  # Handler tests
│   ├── knowledge/                 # Knowledge base tests
│   │   └── test_incident_store.py         # Phase 4: Incident storage tests
│   ├── orchestrator/              # Orchestrator tests
│   │   └── test_alert_correlator.py       # Phase 4: Alert correlation tests
│   └── utils/                     # Utility tests
└── integration/                   # Integration tests (end-to-end)
```

## Running Tests

### Run All Tests
```bash
pytest
```

### Run Specific Test File
```bash
pytest tests/unit/collectors/test_proactive_collector.py
```

### Run Tests by Marker
```bash
# Run only unit tests
pytest -m unit

# Run only async tests
pytest -m asyncio

# Run tests that don't require cluster
pytest -m "not requires_cluster"
```

### Run with Coverage
```bash
# Generate coverage report
pytest --cov=sre_agent --cov-report=html

# View coverage report
open htmlcov/index.html
```

### Run Specific Test
```bash
pytest tests/unit/collectors/test_proactive_collector.py::test_calculate_trend_increasing -v
```

### Run with Different Verbosity
```bash
# Verbose output
pytest -v

# Very verbose (shows all test names)
pytest -vv

# Quiet (minimal output)
pytest -q
```

## Test Categories

### Unit Tests
- **Collectors**: Test observation collection logic
- **Analyzers**: Test diagnosis generation
- **Handlers**: Test remediation execution
- **Knowledge Base**: Test incident storage and retrieval
- **Alert Correlator**: Test alert grouping and root cause detection
- **Utils**: Test utilities (secret scrubbing, RBAC checks, etc.)

### Integration Tests
- End-to-end workflow tests (Collect → Analyze → Handle)
- MCP integration tests
- Database integration tests

## Writing Tests

### Test Naming Convention
- Test files: `test_<module_name>.py`
- Test functions: `test_<functionality>()`
- Async tests: Mark with `@pytest.mark.asyncio`

### Example Unit Test
```python
import pytest
from unittest.mock import AsyncMock

@pytest.mark.asyncio
async def test_collector_returns_observations():
    """Test that collector returns list of observations."""
    mock_registry = AsyncMock()
    collector = MyCollector(mock_registry)

    observations = await collector.collect()

    assert isinstance(observations, list)
    assert len(observations) > 0
```

### Example Integration Test
```python
@pytest.mark.integration
@pytest.mark.asyncio
async def test_full_workflow():
    """Test complete workflow: Collect → Analyze → Handle."""
    # Setup
    workflow_engine = WorkflowEngine(mcp_registry)

    # Execute
    stats = await workflow_engine.run_workflow()

    # Verify
    assert stats["observations"] > 0
```

## Phase 4 Tests

### Proactive Collector Tests
- `test_proactive_collector.py`: Tests for trend detection, anomaly detection, time-to-failure prediction
- Key tests:
  - `test_calculate_trend_increasing()`: Linear regression for trends
  - `test_predict_time_to_limit()`: Time-to-failure calculation
  - `test_detect_anomaly_spike()`: Z-score anomaly detection

### Proactive Analyzer Tests
- `test_proactive_analyzer.py`: Tests for preventive diagnosis
- Key tests:
  - `test_analyze_memory_trend_urgent()`: Urgency calculation
  - `test_analyze_cpu_trend()`: CPU increase recommendations
  - `test_analyze_alert_storm()`: Alert storm handling

### Knowledge Store Tests
- `test_incident_store.py`: Tests for incident learning
- Key tests:
  - `test_store_incident()`: Incident storage
  - `test_find_similar_incidents_exact_match()`: Fingerprint matching
  - `test_get_mttr_statistics()`: MTTR tracking

### Alert Correlator Tests
- `test_alert_correlator.py`: Tests for alert correlation
- Key tests:
  - `test_alert_storm_detection()`: Storm detection (>10 alerts in 5 min)
  - `test_dependency_based_correlation_node_failure()`: Root cause detection
  - `test_deduplication_by_fingerprint()`: Duplicate removal

## Test Fixtures

Common fixtures are available in `conftest.py`:
- `mock_mcp_registry`: Mock MCP tool registry
- `temp_db_path`: Temporary SQLite database path
- `sample_observation`: Sample observation for testing
- `sample_diagnosis`: Sample diagnosis for testing

## Coverage Goals

- **Overall**: >80% code coverage
- **Critical paths**: 100% coverage
  - Secret scrubbing
  - RBAC checks
  - Remediation execution
  - Knowledge base operations

## Continuous Integration

Tests run automatically on:
- Pull requests
- Commits to main branch
- Nightly builds

### CI Configuration
```yaml
# .github/workflows/test.yml
- name: Run tests
  run: |
    pytest --cov=sre_agent --cov-report=xml

- name: Upload coverage
  uses: codecov/codecov-action@v3
```

## Debugging Tests

### Run with PDB on Failure
```bash
pytest --pdb
```

### Show Print Statements
```bash
pytest -s
```

### Run Last Failed Tests
```bash
pytest --lf
```

### Run Tests in Parallel (requires pytest-xdist)
```bash
pytest -n auto
```

## Test Data

Test data files are stored in `tests/fixtures/`:
- Sample YAML manifests
- Mock Prometheus responses
- Sample MCP tool outputs

## Known Issues

- Prometheus integration tests require actual Prometheus instance
- Some MCP integration tests are skipped if MCP servers unavailable
- Alert correlation tests may be timing-sensitive

## Contributing

When adding new features:
1. Write tests FIRST (TDD approach)
2. Ensure tests pass: `pytest`
3. Check coverage: `pytest --cov`
4. Update this README if adding new test categories
