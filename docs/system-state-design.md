# System State and Certainty Architecture

## Problem Statement

LLMs can hallucinate or speculate without evidence. ReOS needs:
1. **Anti-hallucination safeguards**: Wrappers ensuring certainty on LLM output
2. **Comprehensive system state**: All data about the machine available for informed decisions

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                     Certainty Layer                              │
│  ┌───────────────────────────────────────────────────────────┐ │
│  │ CertaintyWrapper                                           │ │
│  │ - Validates claims against known system state              │ │
│  │ - Requires evidence citations for factual claims           │ │
│  │ - Declares uncertainty explicitly when evidence lacking    │ │
│  │ - Confidence scoring on all assertions                     │ │
│  └───────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│                    System State Layer                            │
│                                                                  │
│  ┌─────────────────────────┐  ┌──────────────────────────────┐ │
│  │   Steady State (RAG)    │  │   Volatile State (Tools)     │ │
│  │   Updated: hourly/daily │  │   Updated: on-demand         │ │
│  │                         │  │                              │ │
│  │ • Hostname, domain      │  │ • CPU/Memory usage           │ │
│  │ • OS distro, version    │  │ • Load averages              │ │
│  │ • Kernel version        │  │ • Running processes          │ │
│  │ • CPU model, cores      │  │ • Container states           │ │
│  │ • Total memory          │  │ • Service states             │ │
│  │ • Disk partitions       │  │ • Disk I/O, free space       │ │
│  │ • Network interfaces    │  │ • Network connections        │ │
│  │ • Installed packages    │  │ • Open ports                 │ │
│  │ • Available services    │  │ • Recent logs                │ │
│  │ • Users and groups      │  │ • File changes               │ │
│  │ • System configs        │  │                              │ │
│  └─────────────────────────┘  └──────────────────────────────┘ │
│                                                                  │
│  SteadyState: Always in LLM context (RAG)                       │
│  VolatileState: Fetched via tools when needed                   │
└─────────────────────────────────────────────────────────────────┘
```

## 1. Steady State Data (RAG Context)

Data that changes rarely - collected periodically and stored.

### Categories

| Category | Data Points | Update Frequency |
|----------|-------------|------------------|
| **Identity** | hostname, domain, machine-id | Daily |
| **OS** | distro, version, kernel, arch | Daily |
| **Hardware** | CPU model/cores, memory, disks | Daily |
| **Network Config** | interfaces, IPs, DNS, gateway | Hourly |
| **Packages** | installed packages with versions | Hourly |
| **Services** | available systemd units | Hourly |
| **Users** | users, groups, sudoers | Hourly |
| **Config** | key system configs (fstab, etc.) | Daily |

### Storage

```python
@dataclass
class SteadyState:
    collected_at: datetime
    hostname: str
    domain: str | None
    machine_id: str

    os_name: str        # "Ubuntu"
    os_version: str     # "24.04"
    os_codename: str    # "noble"
    kernel: str         # "6.8.0-45-generic"
    arch: str           # "x86_64"

    cpu_model: str
    cpu_cores: int
    cpu_threads: int
    memory_total_gb: float

    disks: list[DiskInfo]
    network_interfaces: list[NetworkInterface]

    installed_packages: dict[str, str]  # name -> version
    available_services: list[str]

    users: list[UserInfo]
    groups: list[GroupInfo]
```

### RAG Integration

Steady state is serialized to a structured format and included in every LLM prompt:

```
SYSTEM STATE (as of 2024-01-15 10:30:00):
Hostname: corellia.local
OS: Ubuntu 24.04 (noble), kernel 6.8.0-45-generic
CPU: AMD Ryzen 9 5900X (12 cores, 24 threads)
Memory: 64GB
Disks: /dev/nvme0n1 (1TB), /dev/sda (4TB)
Network: eth0 (192.168.1.100), docker0 (172.17.0.1)
Docker: installed (24.0.7)
Packages: 2,847 installed
Services: 156 available (docker.service, nginx.service, ...)
```

## 2. Volatile State (Tool-Accessible)

Data that changes frequently - fetched on-demand via tools.

### Existing Tools (enhance as needed)

| Tool | Data |
|------|------|
| `linux_system_info` | CPU/memory usage, load, uptime |
| `linux_processes` | Running processes |
| `linux_containers` | Docker container states |
| `linux_service_status` | Service state |
| `linux_disk_usage` | Disk space |
| `linux_network_info` | Connections, ports |

### New Tools Needed

| Tool | Data |
|------|------|
| `linux_disk_io` | Disk I/O stats |
| `linux_network_traffic` | Bandwidth usage |
| `linux_recent_logs` | Recent syslog/journald entries |
| `linux_file_changes` | Recently modified files |

## 3. Certainty Wrapper

Ensures LLM output is grounded in evidence.

### Response Structure

```python
@dataclass
class CertainResponse:
    """A response with explicit certainty tracking."""

    answer: str

    # Facts with evidence
    facts: list[Fact]

    # Explicit uncertainties
    uncertainties: list[Uncertainty]

    # Overall confidence
    confidence: float  # 0.0 - 1.0

@dataclass
class Fact:
    claim: str
    evidence_type: str  # "system_state", "tool_output", "user_input"
    evidence_source: str  # "SteadyState.hostname", "linux_containers", etc.
    evidence_value: str

@dataclass
class Uncertainty:
    claim: str
    reason: str  # "no_data", "conflicting_data", "inference"
    confidence: float
```

### Validation Rules

1. **Claims about system state** must cite SteadyState or tool output
2. **Claims about current activity** must cite recent tool output
3. **Inferences** must be explicitly marked as such
4. **Uncertainty** must be declared when:
   - No evidence available
   - Evidence is stale (>5 min for volatile data)
   - Conflicting evidence exists

### Prompt Engineering

```
CRITICAL RULES FOR RESPONSES:
1. Only state facts you can verify from:
   - SYSTEM STATE above (for static facts)
   - Tool outputs (for current state)
   - User's message (for user-provided info)

2. When uncertain, SAY SO explicitly:
   - "I don't have information about X"
   - "Based on [evidence], I believe X, but I'm not certain"
   - "I would need to check Y to confirm"

3. Never guess or speculate about:
   - File contents you haven't read
   - Service states you haven't checked
   - Container configurations you haven't inspected

4. Cite your sources:
   - "According to system state, hostname is X"
   - "The linux_containers tool shows Y"
   - "You mentioned Z in your request"
```

### Post-Processing Validation

After LLM response, wrap with certainty tracking:

```python
def wrap_response(
    response: str,
    system_state: SteadyState | None,
    tool_outputs: list,
    user_input: str
) -> CertainResponse:
    """Wrap LLM response with certainty tracking."""

    # Extract factual claims from response
    claims = self._extract_claims(response)

    facts = []
    uncertainties = []

    for claim in claims:
        evidence = self._find_evidence(claim, system_state, tool_outputs, user_input)
        if evidence and evidence.evidence_type != EvidenceType.NONE:
            facts.append(Fact(claim=claim, evidence=evidence, verified=True))
        else:
            uncertainties.append(Uncertainty(
                claim=claim,
                reason=UncertaintyReason.NO_DATA,
                suggestion=self._suggest_verification(claim),
                confidence=0.3
            ))

    return CertainResponse(
        answer=response,
        facts=facts,
        uncertainties=uncertainties,
        overall_confidence=self._calculate_confidence(facts, uncertainties)
    )
```

## 4. Integration Points

### ChatAgent Changes (Actual Implementation)

```python
class ChatAgent:
    def __init__(self, ...):
        self._steady_state = SteadyStateCollector()
        self._certainty = CertaintyWrapper()
        self._recent_tool_outputs: list[dict] = []

    def respond(self, message: str) -> ChatResponse:
        # Include steady state + certainty rules in context
        system_context = self._get_system_context()  # Calls create_certainty_prompt_addition()

        # ... execute tools, get LLM response ...

        # Validate certainty
        certain_response = self._certainty.wrap_response(
            response=answer,
            system_state=self._steady_state.current,
            tool_outputs=tool_results,
            user_input=user_text,
        )

        return ChatResponse(
            answer=answer,
            confidence=certain_response.overall_confidence,
            evidence_summary=certain_response.evidence_summary,
            has_uncertainties=certain_response.has_uncertainties(),
        )
```

### ReasoningEngine Integration

The ReasoningEngine receives system context (containers, services, packages) from ChatAgent
via `_get_system_snapshot_for_reasoning()`. This provides:
- `container_names`: List of actual container names for matching
- `service_names`: List of actual service names
- `installed_packages`: List of installed packages

The LLMPlanner uses this context to match user references ("nextcloud containers")
against actual system resources, preventing hallucination of non-existent targets.

**Note:** Target validation happens in `LLMPlanner._match_targets()`, not in ReasoningEngine directly.

## 5. Implementation Plan

1. **Phase 1: Steady State Collector**
   - Create `SteadyStateCollector` class
   - Collect all static system data
   - Serialize for LLM context
   - Periodic refresh

2. **Phase 2: Enhanced Tools**
   - Add missing volatile state tools
   - Ensure all tools return structured data
   - Add timestamps to tool outputs

3. **Phase 3: Certainty Wrapper**
   - Create response validation
   - Claim extraction
   - Evidence matching
   - Uncertainty flagging

4. **Phase 4: Integration**
   - Wire into ChatAgent
   - Update prompts
   - Add UI indicators for certainty

## 6. Example Flow

**User**: "Is nginx running?"

**System State (RAG)**:
```
Hostname: corellia
Services available: [..., nginx.service, ...]
```

**LLM decides**: Need current state → calls `linux_service_status(nginx)`

**Tool output**:
```json
{"service": "nginx", "active": true, "running": true, "uptime": "2h 15m"}
```

**Response**:
```
Yes, nginx is running.

[Evidence: linux_service_status tool shows nginx.service is active,
 running for 2 hours 15 minutes]
```

**CertainResponse**:
```python
CertainResponse(
    answer="Yes, nginx is running...",
    facts=[
        Fact(
            claim="nginx is running",
            evidence_type="tool_output",
            evidence_source="linux_service_status",
            evidence_value="active=true, running=true"
        )
    ],
    uncertainties=[],
    confidence=0.95
)
```
