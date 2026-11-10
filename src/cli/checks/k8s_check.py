"""
Kubernetes Configuration Validation
"""
import os
import re

def validate_k8s_file(filepath, check_cfg):
    """
    Validate a single K8s YAML file.
    Since we want to be dependency free (no PyYAML), we use regex to check for 
    common misconfigurations in Deployment manifests.
    """
    require_limits = check_cfg.get("require_limits", True)
    require_probes = check_cfg.get("require_probes", True)
    min_replicas = check_cfg.get("min_replicas", 2)
    expected_namespace = check_cfg.get("namespace", "default")
    
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    # Only validate Deployments for now
    if not re.search(r"^kind:\s*Deployment", content, re.MULTILINE):
        return None
        
    errors = []
    
    # Check namespace
    ns_match = re.search(r"namespace:\s*([^\s]+)", content)
    ns = ns_match.group(1) if ns_match else "default"
    if ns != expected_namespace:
        errors.append(f"Namespace mismatch: got {ns}, expected {expected_namespace}")

    # Check replicas
    rep_match = re.search(r"replicas:\s*(\d+)", content)
    if rep_match:
        replicas = int(rep_match.group(1))
        if replicas < min_replicas:
            errors.append(f"Replicas ({replicas}) < minimum required ({min_replicas})")
            
    # Check for latest tag
    images = re.findall(r"image:\s*([^\s]+)", content)
    for img in images:
        if img.endswith(":latest") or ":" not in img:
            errors.append(f"Image '{img}' uses 'latest' tag or no tag")

    # Check limits
    if require_limits:
        if not re.search(r"limits:", content):
            errors.append("Missing resource limits")
            
    # Check probes
    if require_probes:
        if not re.search(r"livenessProbe:", content):
            errors.append("Missing livenessProbe")
        if not re.search(r"readinessProbe:", content):
            errors.append("Missing readinessProbe")

    return errors

def run_k8s_check(kubeconfig, check_cfg):
    """
    Validate K8s configuration files in a directory or single file against thresholds.
    We reuse the kubeconfig flag as the path to the k8s yaml files for this offline check.
    """
    # For this offline MVP, we treat `kubeconfig` arg as the path to local YAMLs
    # In a full tool, this would connect to the cluster or parse Helm output.
    k8s_path = kubeconfig
    
    if not k8s_path:
        return {"status": "SKIP", "message": "No K8s manifests provided (use --k8s-dir)"}
        
    if not os.path.exists(k8s_path):
        return {"status": "WARN", "message": f"K8s path not found: {k8s_path}"}
        
    files_to_parse = []
    if os.path.isfile(k8s_path):
        if k8s_path.endswith('.yaml') or k8s_path.endswith('.yml'):
            files_to_parse.append(k8s_path)
    else:
        for root, _, files in os.walk(k8s_path):
            for file in files:
                if file.endswith('.yaml') or file.endswith('.yml'):
                    files_to_parse.append(os.path.join(root, file))

    if not files_to_parse:
        return {"status": "SKIP", "message": "No .yaml files found in K8s path"}

    all_errors = []
    scanned_count = 0
    
    for filepath in files_to_parse:
        errors = validate_k8s_file(filepath, check_cfg)
        if errors is not None:
            scanned_count += 1
            if errors:
                filename = os.path.basename(filepath)
                all_errors.append(f"{filename}: " + ", ".join(errors))

    if scanned_count == 0:
        return {"status": "SKIP", "message": "No Deployment manifests found to scan"}

    if all_errors:
        return {"status": "FAIL", "message": " | ".join(all_errors)}

    return {"status": "PASS", "message": f"{scanned_count} deployments passed validation"}
