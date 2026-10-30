# Google Earth Engine tool integration

AutoGIS now has local credential configuration and callable Earth Engine tools.
The helpers in `core/gee_tools.py` initialize the configured project and expose:
- `tool_gee_image_collection`: query an image collection by date and bounding box.
- `tool_gee_image_preview`: generate a thumbnail URL for a selected image.

Requirements:
- Install `earthengine-api` into the Python environment used by QGIS.
- Enable the Earth Engine API and authorize the Cloud project with Google.
- Set the project ID in AutoGIS Settings and authenticate with OAuth or a service account.
- A service account must have the required Earth Engine access and access to private assets.

These are callable helpers; a tool registry or AI planner must explicitly register and expose them to the assistant before users can invoke them through natural-language chat. Earth Engine requests can incur quota and computation costs. Keep bounding boxes and result sizes small, and do not call `getInfo()` on unbounded collections.
