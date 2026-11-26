def _authenticated(context, data_dict):
    if not context.get("user"):
        return {"success": False, "msg": "Authentication required"}
    return {"success": True}


def get_auth_functions():
    return {name: _authenticated for name in (
        "dataset_transfer_targets", "dataset_transfer_validate",
        "dataset_transfer_publish", "dataset_transfer_status",
    )}
