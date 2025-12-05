# LabelMate Scene — Home Assistant custom integration

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
![Home Assistant](https://img.shields.io/badge/Home%20Assistant-Custom%20Component-41BDF5)


## Overview
LabelMate Scene provides a small integration that creates logical groups of switches or lights driven by Home Assistant "labels" or can be tied more specifically to scenes. It dynamically watches entities that have a given label and/or scene.

- A Switch or Light entity (depending on the selected group type) that controls all matched entities.
- Two sensors: active count (number of matched entities that are "on") and total count (number of matched entities).

This integration prefers scenes when turning the group on/off: if you add scenes that have the same label, the integration will attempt to activate a matching scene instead of directly toggling members ON or OFF. If there is no scene, it directly toggles the tagged members on or off. See Notes on Behavior below.

In **Scene Mode**, the integration creates one switch per label that aggregates all entities from multiple scenes sharing that label. Turning the switch ON activates the first scene alphabetically; turning it OFF deactivates all aggregated entities across all matching scenes.

## Group Types

**Switch/Light:**
- Scans for entities which are using the configured label
- Creates a switch or light which appears as a group in the UI
- In its default (no labeled scene found) state will turn on as soon as any labeled light or switch is ON and OFF when all are off
- Will search for a scene with the SAME label and if "off" is not found in the name, activate the scene, even if that means not all devices are in that scene or label.
- When turning it OFF, it will search for a scene with the configured label and if "off" is found in the name, use it will activate the scene, even if that means not all devices are in that scene or label and will continue to represent the state of the labeled devices.

**Scene Mode:**
- Scans for **all scenes** that have the configured label
- Creates **one switch per label** (not per scene) that aggregates entities from all matching scenes
- The group includes all unique entities and devices from every scene with that label
- **Turning ON**: Activates the **first scene alphabetically** from all scenes with that label
- **Turning OFF**: Turns off **ALL entities** aggregated from all scenes with that label (can span multiple scenes)
- Properly handles both individual entities and devices added to scenes
- Dynamically updates when scenes are added, removed, or modified

## Status & Notes
This integration is actively evolving. Scene-only groups may report zero-valued sensors; behavior and corner cases continue to be refined. Use at your own risk; your mileage may vary.

## Installation
Manual installation

1. Copy the `labelmate_scene` folder into your Home Assistant `custom_components` directory so the layout is:

```text
custom_components/labelmate_scene/
  __init__.py
  manifest.json
  config_flow.py
  const.py
  group_base.py
  entity_manager.py
  light.py
  switch.py
  sensor.py
  strings.json
  translations/en.json
```

2. Restart Home Assistant.

3. In Home Assistant go to Settings → Devices & Services → Add integration and search for "LabelMate Scene".

HACS
----
If/when this project is published to HACS, install it from HACS and restart Home Assistant. Then add the integration via Settings → Devices & Services like above.

## Configuration
1. Add a label to the entities you want to include. Labels are Home Assistant metadata attached to entities. You can add labels using the entity editor in the UI (Settings → Devices & Services → Entities → select an entity → Edit → Labels) or via the Entity Registry.

2. Add the LabelMate Scene integration from the UI. In the config flow you will be asked for:

- Label Name: the exact label text (case-insensitive) used to select entities.
- Group Type: "Switch", "Light", or "Scene"

3. After creating the config entry, the integration will create:

- A switch or light entity named "Label <label_name> Group".
- Two sensors named like `sensor.label_<label_name_safe>_group_active_count` and `sensor.label_<label_name_safe>_group_total_count`.

4. Use the integration's Options to set the light color (hex). Helpful for dashboards/themes (e.g., holiday strings).

## Demo
[![Demo](./.assets/demo.gif)](./.assets/demo.mp4)


## Notes on behavior
- Membership is dynamic and event-driven: the integration watches the entity/device/label registries and state changes to recompute which entities match the label. It filters to allowed domains (lights, switches, fans, input_booleans by default).
- The "Light" variant reports a computed `brightness` and supports RGB color in the UI (color is configurable as options on the config entry).
- When turning the group ON or OFF (for Switch/Light types), the integration first attempts to find a Scene that matches the same label. Matching rules:
  - Scene entity must have the same label attached.
  - For ON actions: the scene name must NOT contain the word "off" (case-insensitive).
  - For OFF actions: the scene name MUST contain the word "off".
  - If multiple matches exist, the integration picks the first alphabetical scene entity id.
- **Scene Mode behavior:**
  - Creates one switch per label that aggregates entities from all scenes with that label
  - Supports both entities and devices added to scenes (devices are expanded to their constituent entities)
  - Turn ON: Activates the first alphabetically-sorted scene
  - Turn OFF: Deactivates all entities from all scenes with that label
  - The switch state reflects whether any aggregated entities are currently on

## Troubleshooting
- The integration matches labels using Home Assistant's label system. If you do not see expected entities, verify the label is attached to the entity (check Settings → Devices & Services → Entities and confirm the "Labels" field).
- If the group's entity shows zero total members, verify that matched entities are in allowed domains: the integration filters to a small set (light, switch, fan, input_boolean) by default. You can change `ALLOWED_DOMAINS` in `const.py` to include other domains if needed.
- Scene activation rules: Scene matching is based on labels attached to the scene entity. If scenes are not being activated, ensure the scene entity has the label set in the entity registry.
- **Scene Mode**: If entities aren't being detected from scenes, ensure the scene includes actual entities or devices. The integration extracts both direct entity references and expands device references to their constituent entities.

Improvement Ideas
-----------------
- Add support for areas
- Expose the suppression window as an option per-entry so users can tune optimistic UI timing.
- Add unit tests that mock `hass.states` and the template rendering to verify membership, sensors, and scene selection logic.
- Consider adding an option to include additional domains or to configure the allowed domains from the UI.

Todos
-----
Current tasks and status for this integration repository:
- [ ] Evaluate adding area support — Assess how to add area-based groups (design, API usage, config flow, migration, tests). (in progress)
- [x] ~~Fix zero sensor values for the Scene option~~ — Scene mode now aggregates entities properly
- [x] ~~Move to one switch per label instead of per scene~~ — Implemented with entity aggregation across scenes
- [ ] Move Sensor values tied to switch and light options to an attribute on the Light or Switch. Will improve support for the Scene option where we might have multiple switches on a single device.
