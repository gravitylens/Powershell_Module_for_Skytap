import base64
import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime
import socket
from ftplib import FTP

import requests


class SkytapClient:
    """Simple Python client for the Skytap REST API."""

    def __init__(self, base_url: str = "https://cloud.skytap.com", logfile: str = "skytap.log") -> None:
        self.base_url = base_url.rstrip("/")
        self.headers: Dict[str, str] = {"Accept": "application/json"}
        self.logfile = logfile

    def log_write(self, message: str) -> None:
        """Append a timestamped message to the configured log file."""
        ts = datetime.now().isoformat()
        with open(self.logfile, "a", encoding="utf-8") as fh:
            fh.write(f"{ts}  {message}\n")

    def show_request_failure(self, exc: Exception) -> Dict[str, Any]:
        """Return structured information about a failed request."""
        if isinstance(exc, requests.HTTPError):
            resp = exc.response
            return {
                "requestResultCode": resp.status_code if resp else -1,
                "eDescription": resp.reason if resp else str(exc),
                "eMessage": resp.text if resp else str(exc),
                "method": resp.request.method if resp and resp.request else "",
            }
        return {
            "requestResultCode": getattr(exc, "errno", -1),
            "eDescription": exc.__class__.__name__,
            "eMessage": str(exc),
            "method": "",
        }

    def show_web_request_failure(self, exc: Exception) -> Dict[str, Any]:
        """Simplified failure information used by the PowerShell module."""
        if isinstance(exc, requests.HTTPError) and exc.response is not None:
            return {
                "requestResultCode": exc.response.status_code,
                "eDescription": exc.response.reason,
            }
        return {
            "requestResultCode": -1,
            "eDescription": str(exc),
        }

    def set_authorization(
        self, tokenfile: str = "user_token", user: Optional[str] = None, password: Optional[str] = None
    ) -> None:
        """Load credentials from a token file or explicit parameters."""
        if user is None:
            path = Path(tokenfile)
            if not path.exists():
                raise FileNotFoundError(f"The user_token file {tokenfile} was not found")
            creds = {}
            for line in path.read_text().splitlines():
                if "=" in line:
                    k, v = line.split("=", 1)
                    creds[k.strip()] = v.strip()
            user = creds.get("username")
            password = creds.get("password")
        if user is None or password is None:
            raise ValueError("Username and password required")
        token = base64.b64encode(f"{user}:{password}".encode("ascii")).decode("ascii")
        self.headers["Authorization"] = f"Basic {token}"

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        url = f"{self.base_url}{path}"
        resp = requests.request(method, url, headers=self.headers, **kwargs)
        resp.raise_for_status()
        if resp.text:
            return resp.json()
        return None

    def add_configuration_to_project(self, config_id: str, project_id: str) -> Any:
        return self._request(
            "POST", f"/projects/{project_id}/configurations/{config_id}"
        )

    def copy_configuration(self, config_id: str, vm_ids: Optional[List[str]] = None) -> Any:
        body: Dict[str, Any] = {"configuration_id": config_id}
        if vm_ids:
            body["vm_ids"] = vm_ids
        return self._request("POST", "/configurations", json=body)

    def edit_configuration(self, config_id: str, attributes: Dict[str, Any]) -> Any:
        return self._request("PUT", f"/configurations/{config_id}", json=attributes)

    def edit_vm(self, config_id: str, vm_id: str, attributes: Dict[str, Any]) -> Any:
        return self._request(
            "PUT", f"/configurations/{config_id}/vms/{vm_id}/", json=attributes
        )

    def update_run_state(self, config_id: str, new_state: str, vm_id: Optional[str] = None) -> Any:
        path = f"/configurations/{config_id}"
        if vm_id:
            path += f"/vms/{vm_id}"
        body = {"runstate": new_state}
        return self._request("PUT", path, json=body)
    def get_projects(self, project_id: Optional[str] = None) -> Any:
        path = f"/projects/{project_id}" if project_id else "/projects"
        return self._request("GET", path)

    def get_vms(self, config_id: str, vm_id: Optional[str] = None) -> Any:
        path = f"/configurations/{config_id}/vms"
        if vm_id:
            path += f"/{vm_id}"
        return self._request("GET", path)

    def get_project_environments(self, project_id: str) -> Any:
        path = f"/projects/{project_id}/configurations"
        return self._request("GET", path)
    def add_network_adapter(self, config_id: str, vm_id: str, nic_type: str = "default") -> Any:
        body = {"nic_type": nic_type}
        return self._request("POST", f"/configurations/{config_id}/vms/{vm_id}/interfaces", json=body)

    def edit_network_adapter(self, config_id: str, vm_id: str, interface_id: str, attributes: Dict[str, Any]) -> Any:
        return self._request(
            "PUT",
            f"/configurations/{config_id}/vms/{vm_id}/interfaces/{interface_id}",
            json=attributes,
        )

    def edit_vm_userdata(self, config_id: str, vm_id: str, contents: str) -> Any:
        return self._request(
            "PUT",
            f"/configurations/{config_id}/vms/{vm_id}/user_data",
            json={"contents": contents},
        )

    def connect_network(self, source_network: str, destination_network: str) -> Any:
        body = {"source_network_id": source_network, "target_network_id": destination_network}
        return self._request("POST", "/tunnels", json=body)

    def remove_network(self, tunnel_id: str) -> Any:
        return self._request("DELETE", f"/tunnels/{tunnel_id}")

    def create_environment_from_template(self, template_id: str) -> Any:
        return self._request("POST", "/configurations", json={"template_id": template_id})

    def create_project(self, name: str, description: str = "") -> Any:
        return self._request("POST", "/projects", json={"name": name, "summary": description})

    def publish_url(
        self,
        config_id: str,
        publish_set_type: str = "single_url",
        name: Optional[str] = None,
        sso: bool = False,
    ) -> Any:
        if name is None:
            name = f"Published set - {publish_set_type}"
        body = {"name": name, "publish_set_type": publish_set_type}
        if sso:
            body["sso_required"] = True
        return self._request("POST", f"/configurations/{config_id}/publish_sets", json=body)

    def save_configuration_to_template(
        self,
        config_id: str,
        vm_ids: List[str],
        networks: str = "none",
        name: str = "",
    ) -> Any:
        body = {
            "configuration_id": config_id,
            "vm_ids": vm_ids,
            "network_option": networks,
            "template_name": name,
        }
        return self._request("POST", "/templates", json=body)

    def remove_configuration(self, config_id: str) -> Any:
        return self._request("DELETE", f"/configurations/{config_id}")

    def remove_template(self, template_id: str) -> Any:
        return self._request("DELETE", f"/templates/{template_id}")

    def remove_project(self, project_id: str) -> Any:
        return self._request("DELETE", f"/projects/{project_id}")

    def add_template_to_project(self, project_id: str, template_id: str) -> Any:
        return self._request("POST", f"/projects/{project_id}/templates/{template_id}")

    def add_template_to_configuration(self, config_id: str, template_id: str) -> Any:
        return self._request("POST", f"/configurations/{config_id}/templates/{template_id}")

    def get_configurations(self, config_id: Optional[str] = None) -> Any:
        path = f"/configurations/{config_id}" if config_id else "/configurations"
        return self._request("GET", path)

    def get_templates(self, template_id: Optional[str] = None) -> Any:
        path = f"/templates/{template_id}" if template_id else "/templates"
        return self._request("GET", path)

    def get_vm_user_data(self, config_id: str, vm_id: str) -> Any:
        return self._request("GET", f"/configurations/{config_id}/vms/{vm_id}/user_data")

    def get_published_urls(self, config_id: str) -> Any:
        return self._request("GET", f"/configurations/{config_id}/publish_sets")

    def get_published_url_details(self, publish_set_id: str) -> Any:
        return self._request("GET", f"/publish_sets/{publish_set_id}")

    def get_published_services(self, config_id: str, vm_id: str, interface_id: str) -> Any:
        path = f"/configurations/{config_id}/vms/{vm_id}/interfaces/{interface_id}/services"
        return self._request("GET", path)

    def get_department_quotas(self, department_id: str) -> Any:
        return self._request("GET", f"/departments/{department_id}/quotas")

    def get_departments(self, department_id: Optional[str] = None) -> Any:
        path = f"/departments/{department_id}" if department_id else "/departments"
        return self._request("GET", path)

    def get_users(self, user_id: Optional[str] = None) -> Any:
        path = f"/users/{user_id}" if user_id else "/users"
        return self._request("GET", path)

    def add_user(
        self,
        login_name: str,
        first_name: str,
        last_name: str,
        email: str,
        account_role: str = "restricted_user",
        can_import: bool = False,
        can_export: bool = False,
        time_zone: str = "Pacific Time (US & Canada)",
        region: str = "US-West",
    ) -> Any:
        body = {
            "login_name": login_name,
            "first_name": first_name,
            "last_name": last_name,
            "email": email,
            "account_role": account_role,
            "can_import": can_import,
            "can_export": can_export,
            "time_zone": time_zone,
            "region": region,
        }
        return self._request("POST", "/users", json=body)

    def add_group(self, group_name: str, description: str = "") -> Any:
        return self._request("POST", "/groups", json={"name": group_name, "description": description})

    def add_department(self, department_name: str, description: str = "") -> Any:
        return self._request("POST", "/departments", json={"name": department_name, "description": description})

    def add_environment_tag(self, config_id: str, tags: List[str]) -> Any:
        return self._request("POST", f"/configurations/{config_id}/tags", json={"tags": tags})

    def add_template_tag(self, template_id: str, tags: List[str]) -> Any:
        return self._request("POST", f"/templates/{template_id}/tags", json={"tags": tags})

    def get_tags(
        self,
        config_id: Optional[str] = None,
        template_id: Optional[str] = None,
        asset_id: Optional[str] = None,
    ) -> Any:
        if config_id:
            return self._request("GET", f"/configurations/{config_id}/tags")
        if template_id:
            return self._request("GET", f"/templates/{template_id}/tags")
        if asset_id:
            return self._request("GET", f"/assets/{asset_id}/tags")
        return None

    def get_vm_credentials(self, vm_id: str) -> Any:
        return self._request("GET", f"/vms/{vm_id}/credentials")

    def attach_wan(self, env_id: str, network_id: str, wan_id: str) -> Any:
        return self._request(
            "POST",
            f"/configurations/{env_id}/networks/{network_id}/wans/{wan_id}",
        )

    def connect_wan(self, env_id: str, network_id: str, wan_id: str) -> Any:
        return self._request(
            "POST",
            f"/configurations/{env_id}/networks/{network_id}/wans/{wan_id}/connect",
        )

    def get_wan(self, wan_id: str) -> Any:
        return self._request("GET", f"/wans/{wan_id}")

    def get_network(self, config_id: str, network_id: str) -> Any:
        return self._request("GET", f"/configurations/{config_id}/networks/{network_id}")

    def update_environment_userdata(self, config_id: str, userdata: Dict[str, Any]) -> Any:
        return self._request(
            "PUT", f"/configurations/{config_id}/user_data", json=userdata
        )

    def rename_environment(self, config_id: str, new_name: str) -> Any:
        """Rename an environment."""
        body = {"name": new_name}
        return self._request("PUT", f"/configurations/{config_id}", json=body)

    def update_auto_suspend(self, config_id: str, suspend_on_idle: int) -> Any:
        """Set auto suspend timeout in seconds."""
        body = {"suspend_on_idle": suspend_on_idle}
        return self._request("PUT", f"/configurations/{config_id}", json=body)

    def add_user_to_project(
        self, project_id: str, user_id: str, project_role: str = "participant"
    ) -> Any:
        """Add a user to a project with the given role."""
        body = {"role": project_role}
        return self._request(
            "POST", f"/projects/{project_id}/users/{user_id}", json=body
        )

    def add_user_to_group(self, group_id: str, user_id: str) -> Any:
        """Add a user to a group."""
        return self._request(
            "POST", f"/groups/{group_id}/users/{user_id}", json={}
        )

    def get_metadata(self) -> Any:
        """Retrieve VM metadata from inside a Skytap VM."""
        host_ip = socket.gethostbyname(socket.gethostname())
        octets = host_ip.split(".")
        meta_ip = f"{octets[0]}.{octets[1]}.{octets[2]}.254"
        resp = requests.get(f"http://{meta_ip}/skytap")
        resp.raise_for_status()
        return resp.json()

    def send_shared_drive(
        self,
        local_filename: str,
        remote_filename: str,
        ftp_region: str,
        ftp_user: str,
        ftp_password: str,
    ) -> None:
        """Upload a file to the Skytap shared drive via FTP."""
        with FTP(ftp_region) as ftp:
            ftp.login(ftp_user, ftp_password)
            ftp.cwd("shared_drive")
            with open(local_filename, "rb") as fh:
                ftp.storbinary(f"STOR {remote_filename}", fh)

    def add_schedule(
        self,
        object_id: str,
        title: str,
        schedule_actions: List[Dict[str, Any]],
        start_at: str,
        *,
        stype: str = "config",
        recurring_days: Optional[str] = None,
        end_at: Optional[str] = None,
        timezone: str = "Pacific Time (US & Canada)",
        delete_at_end: bool = False,
    ) -> Any:
        """Create a schedule for a configuration or template."""
        body: Dict[str, Any] = {
            "title": title,
            "start_at": start_at,
            "time_zone": timezone,
            "actions": schedule_actions,
        }
        if stype == "config":
            body["configuration_id"] = object_id
        else:
            body["template_id"] = object_id
        if end_at:
            body["end_at"] = end_at
        if recurring_days:
            body["recurring_days"] = recurring_days
        if delete_at_end:
            body["delete_at_end"] = True
        return self._request("POST", "/schedules", json=body)

    def get_usage(
        self,
        rid: str = "0",
        start_at: Optional[str] = None,
        end_at: Optional[str] = None,
        resource: str = "svms",
        region: str = "all",
        agg: str = "month",
        groupby: str = "user",
        fmt: str = "csv",
    ) -> Any:
        """Create or retrieve a usage report."""
        if rid == "0":
            body = {
                "start_date": start_at,
                "end_date": end_at,
                "resource_type": resource,
                "region": region,
                "group_by": groupby,
                "aggregate_by": agg,
                "results_format": fmt,
                "utc": True,
                "notify_by_email": False,
            }
            return self._request("POST", "/reports", json=body)
        result = self._request("GET", f"/reports/{rid}")
        if isinstance(result, dict) and result.get("ready"):
            return self._request("GET", f"/reports/{rid}.csv")
        return result

    def get_audit_report(
        self,
        rid: str = "0",
        start_at: Optional[datetime] = None,
        end_at: Optional[datetime] = None,
        activity: str = "",
    ) -> Any:
        """Create or retrieve an audit report."""
        if rid == "0":
            if not (start_at and end_at):
                raise ValueError("start_at and end_at are required for new report")
            body = {
                "date_start": {
                    "year": start_at.year,
                    "month": start_at.month,
                    "day": start_at.day,
                    "hour": start_at.hour,
                    "minute": start_at.minute,
                },
                "date_end": {
                    "year": end_at.year,
                    "month": end_at.month,
                    "day": end_at.day,
                    "hour": end_at.hour,
                    "minute": end_at.minute,
                },
                "activity": activity,
                "notify_by_email": False,
            }
            return self._request("POST", "/auditing/exports", json=body)
        result = self._request("GET", f"/auditing/exports/{rid}")
        if isinstance(result, dict) and result.get("ready"):
            return self._request("GET", f"/auditing/exports/{rid}.csv")
        return result

    def get_public_ips(self) -> Any:
        """Return the list of public IPs for the account."""
        return self._request("GET", "/ips")

    def get_schedules(self, schedule_id: Optional[str] = None) -> Any:
        path = f"/schedules/{schedule_id}" if schedule_id else "/schedules"
        return self._request("GET", path)

    def connect_public_ip(self, vm_id: str, interface_id: str, public_ip: str) -> Any:
        body = {"ip": public_ip}
        return self._request(
            "POST",
            f"/vms/{vm_id}/interfaces/{interface_id}/ips",
            json=body,
        )

    def publish_service(
        self,
        config_id: str,
        vm_id: str,
        interface_id: str,
        service_id: str,
        port: str,
    ) -> Any:
        body = {"port": port}
        return self._request(
            "POST",
            f"/configurations/{config_id}/vms/{vm_id}/interfaces/{interface_id}/services/{service_id}",
            json=body,
        )

    def remove_tag(self, config_id: str, tag_id: str) -> Any:
        if tag_id.lower() == "all":
            tags = self.get_tags(config_id=config_id) or []
            results = []
            for tag in tags:
                tid = tag.get("id") if isinstance(tag, dict) else tag
                try:
                    results.append(
                        self._request(
                            "DELETE",
                            f"/configurations/{config_id}/tags/{tid}",
                        )
                    )
                except requests.HTTPError:
                    results.append(None)
            return results
        return self._request(
            "DELETE", f"/configurations/{config_id}/tags/{tag_id}"
        )
