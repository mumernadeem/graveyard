"""
Cost Estimation Check
Estimates monthly cloud cost based on K8s resource requests in deployment YAMLs.

Pricing can come from three sources (priority order):
1. User-provided pricing in .graveyard.yml (exact costs for their infra)
2. Provider presets (aws, gcp, azure, hetzner, digitalocean)
3. Fallback blended average rates
"""
import os
import re


HOURS_PER_MONTH = 730  # 365.25 * 24 / 12

# ─── Provider pricing presets (on-demand, general-purpose, 2026 rates) ──
PROVIDER_PRESETS = {
    "aws": {
        "name": "AWS (m6i/m7i average)",
        "vcpu_hour":  0.0384,     # ~$28.03/mo per vCPU
        "gb_ram_hour": 0.00512,   # ~$3.74/mo per GB
        "currency": "USD",
    },
    "gcp": {
        "name": "GCP (e2/n2 average)",
        "vcpu_hour":  0.0335,     # ~$24.46/mo per vCPU
        "gb_ram_hour": 0.00449,   # ~$3.28/mo per GB
        "currency": "USD",
    },
    "azure": {
        "name": "Azure (D-series average)",
        "vcpu_hour":  0.0384,     # ~$28.03/mo per vCPU
        "gb_ram_hour": 0.00512,   # ~$3.74/mo per GB
        "currency": "USD",
    },
    "hetzner": {
        "name": "Hetzner Cloud (CX/CPX)",
        "vcpu_hour":  0.0068,     # ~$4.96/mo per vCPU
        "gb_ram_hour": 0.0034,    # ~$2.48/mo per GB
        "currency": "EUR",
    },
    "digitalocean": {
        "name": "DigitalOcean (Droplets)",
        "vcpu_hour":  0.0119,     # ~$8.69/mo per vCPU
        "gb_ram_hour": 0.00595,   # ~$4.34/mo per GB
        "currency": "USD",
    },
    "linode": {
        "name": "Linode/Akamai",
        "vcpu_hour":  0.0109,     # ~$7.96/mo per vCPU
        "gb_ram_hour": 0.00545,   # ~$3.98/mo per GB
        "currency": "USD",
    },
    "blended": {
        "name": "Blended Average (AWS/GCP/Azure)",
        "vcpu_hour":  0.035,
        "gb_ram_hour": 0.0045,
        "currency": "USD",
    },
}


def get_pricing(check_cfg):
    """
    Resolve pricing rates from config. Priority:
    1. User-provided custom rates (vcpu_hour + gb_ram_hour)
    2. Provider preset name
    3. Fallback to blended average
    
    Config example in .graveyard.yml:
    
      cost:
        enabled: true
        provider: aws                    # Use a preset
        # OR provide your own rates:
        # vcpu_hour: 0.042
        # gb_ram_hour: 0.006
        # node_monthly: 150              # Or just total per-node cost
        # node_vcpus: 4
        # node_ram_gb: 16
        # currency: USD
        warn_threshold: 100
    """
    # Option 1: User provides per-node cost → derive per-resource rates
    if check_cfg.get("node_monthly"):
        node_cost = float(check_cfg["node_monthly"])
        node_vcpus = float(check_cfg.get("node_vcpus", 4))
        node_ram_gb = float(check_cfg.get("node_ram_gb", 16))
        currency = check_cfg.get("currency", "USD")
        provider_name = check_cfg.get("provider", "custom")

        # Distribute cost proportionally: 70% to CPU, 30% to RAM
        cpu_share = 0.7
        ram_share = 0.3
        vcpu_hour = (node_cost * cpu_share) / (node_vcpus * HOURS_PER_MONTH)
        gb_ram_hour = (node_cost * ram_share) / (node_ram_gb * HOURS_PER_MONTH)

        return {
            "name": f"{provider_name} (custom: ${node_cost:.0f}/mo per node, {node_vcpus}vCPU, {node_ram_gb}GB)",
            "vcpu_hour": vcpu_hour,
            "gb_ram_hour": gb_ram_hour,
            "currency": currency,
        }

    # Option 2: User provides exact hourly rates
    if check_cfg.get("vcpu_hour") and check_cfg.get("gb_ram_hour"):
        return {
            "name": check_cfg.get("provider", "custom") + " (custom rates)",
            "vcpu_hour": float(check_cfg["vcpu_hour"]),
            "gb_ram_hour": float(check_cfg["gb_ram_hour"]),
            "currency": check_cfg.get("currency", "USD"),
        }

    # Option 3: Provider preset
    provider = str(check_cfg.get("provider", "blended")).lower().strip()
    if provider in PROVIDER_PRESETS:
        return PROVIDER_PRESETS[provider]

    # Fallback
    return PROVIDER_PRESETS["blended"]


def parse_cpu(cpu_str):
    """Convert K8s CPU string to vCPU float. e.g. '500m' -> 0.5, '2' -> 2.0"""
    cpu_str = str(cpu_str).strip().strip('"').strip("'")
    if cpu_str.endswith("m"):
        return float(cpu_str[:-1]) / 1000.0
    return float(cpu_str)


def parse_memory(mem_str):
    """Convert K8s memory string to GB float. e.g. '128Mi' -> 0.125, '1Gi' -> 1.0"""
    mem_str = str(mem_str).strip().strip('"').strip("'")

    multipliers = {
        "Ki": 1 / (1024 * 1024),
        "Mi": 1 / 1024,
        "Gi": 1,
        "Ti": 1024,
        "K":  1 / (1000 * 1000),
        "M":  1 / 1000,
        "G":  1,
        "T":  1000,
    }

    for suffix, mult in sorted(multipliers.items(), key=lambda x: -len(x[0])):
        if mem_str.endswith(suffix):
            return float(mem_str[:-len(suffix)]) * mult

    try:
        return float(mem_str) / (1024 ** 3)
    except ValueError:
        return 0.0


def extract_resources_from_yaml(filepath):
    """
    Extract CPU/memory requests and replica count from a K8s deployment YAML.
    Uses regex since we have no PyYAML dependency.
    """
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    if not re.search(r"^kind:\s*Deployment", content, re.MULTILINE):
        return None

    result = {"replicas": 1, "containers": [], "filename": os.path.basename(filepath)}

    rep_match = re.search(r"replicas:\s*(\d+)", content)
    if rep_match:
        result["replicas"] = int(rep_match.group(1))

    container_names = re.findall(r"-\s*name:\s*(\S+)", content)
    cpu_requests = re.findall(r"cpu:\s*[\"']?(\S+?)[\"']?\s*$", content, re.MULTILINE)
    mem_requests = re.findall(r"memory:\s*[\"']?(\S+?)[\"']?\s*$", content, re.MULTILINE)

    cpu_val = parse_cpu(cpu_requests[0]) if cpu_requests else 0.0
    mem_val = parse_memory(mem_requests[0]) if mem_requests else 0.0

    container_name = container_names[0] if container_names else "main"
    result["containers"].append({
        "name": container_name,
        "cpu": cpu_val,
        "memory_gb": mem_val,
    })

    return result


def calculate_monthly_cost(cpu_vcpu, memory_gb, replicas, pricing):
    """Calculate estimated monthly cost for a given resource allocation."""
    cpu_cost = cpu_vcpu * pricing["vcpu_hour"] * HOURS_PER_MONTH
    mem_cost = memory_gb * pricing["gb_ram_hour"] * HOURS_PER_MONTH
    per_pod = cpu_cost + mem_cost
    total = per_pod * replicas
    return per_pod, total


def run_cost_check(k8s_dir, check_cfg):
    """
    Estimate deployment cost based on K8s resource requests.
    Uses pricing from config (user-provided, provider preset, or blended average).
    """
    if not k8s_dir:
        return {"status": "SKIP", "message": "No K8s manifests provided (use --k8s-dir for cost estimation)"}

    if not os.path.exists(k8s_dir):
        return {"status": "SKIP", "message": f"K8s path not found: {k8s_dir}"}

    warn_threshold = float(check_cfg.get("warn_threshold", 100))
    pricing = get_pricing(check_cfg)
    currency = pricing.get("currency", "USD")
    currency_sym = "€" if currency == "EUR" else "$"

    # Collect YAML files
    files = []
    if os.path.isfile(k8s_dir):
        if k8s_dir.endswith(('.yaml', '.yml')):
            files.append(k8s_dir)
    else:
        for root, _, filenames in os.walk(k8s_dir):
            for f in filenames:
                if f.endswith(('.yaml', '.yml')):
                    files.append(os.path.join(root, f))

    if not files:
        return {"status": "SKIP", "message": "No YAML files found"}

    total_monthly = 0.0
    breakdowns = []

    for filepath in files:
        resources = extract_resources_from_yaml(filepath)
        if resources is None:
            continue

        replicas = resources["replicas"]
        for container in resources["containers"]:
            cpu = container["cpu"]
            mem = container["memory_gb"]

            if cpu == 0 and mem == 0:
                breakdowns.append(f"{container['name']}: no resource requests defined")
                continue

            per_pod, total = calculate_monthly_cost(cpu, mem, replicas, pricing)
            total_monthly += total
            breakdowns.append(
                f"{container['name']}: {cpu}vCPU + {mem:.2f}GB × {replicas}r = {currency_sym}{total:.2f}/mo"
            )

    if not breakdowns:
        return {"status": "SKIP", "message": "No Deployment manifests found for cost estimation"}

    provider_label = pricing["name"]
    summary = " | ".join(breakdowns)
    total_str = f"{currency_sym}{total_monthly:.2f}/mo"

    msg = f"Estimated {total_str} [{provider_label}] — {summary}"

    if total_monthly > warn_threshold:
        return {
            "status": "WARN",
            "message": f"{msg} (threshold: {currency_sym}{warn_threshold:.0f})"
        }

    return {"status": "PASS", "message": msg}
