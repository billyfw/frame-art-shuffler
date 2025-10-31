temp

Now that we have tv commands working well in #file:frame_art_shuffler, I'd like to take the next step to make it a working integration, as follows. Don't do it - please provide thoughts on what I spell out, including: 

--Is this similar to a typical HA integration? In what ways yes and in what ways no?
-- What will be the interface between the integration and HA - any risks there?
-- Will the plan of how it interacts with HA (#ha-config) and the frame-art-manager add on of ours (ha-config/www/frame_art) work well? any risks there? 
-- what else should i think about in integration design that this design doesn't cover? 

DESIGN: 

A. Integration 
The integration should read #metadata.json of the frame-art-manager add on (tell me if you cannot find it in the workspace), which has as objects, TVs and images. 

For each TV, expose a frame-art-shuffler object (i'm not sure how to do this -- is each an entity of that type? what are the options?), with the following attributes: 
--current_image
--on/off
--update_frequency
--image_last_updated_time
--image_next_scheduled_update_time
--display_tags
--exclude_tags

the integration, frame-art-shuffler, should expose services (are services correct? methods/functions?) which should be all implementable via our #frame_tv.py: 
-- set_art_on_tv_delete_others, which accepts an image id or path and tv
-- get_random_art_file, which accepts a tv to provide a file for
-- set_brightness_on_tv, which accepts a tv and a brightness
-- tv_on/off

B. Logging

The integration should write to a log file, log.json, of a similar format (or propose a better one) for ease of displaying logs by tv or by image: 
tvs {
    tv {
        timestamp: set to img3 
        timestamp: set to image4
    }
    tv {
        timestamp: set to image2
        timestamp: etc
    }
}
images {
    image1 {
        showings  {
            {
            tv: tv1
            start time: 8am
            end time: 10am
            }
        }
    }
}
where should this file live? 

it should be readable by our add on, since I'll want to expose log info in the add on's interface. this is probably atypical rather than using HAs logging?

C. Add on scheduling
In order to implement the actual scheduling of shuffling of art, that will happen in the add-on, which will fire an event, so an HA automation can appropriately call this integration. We don't have to implement that yet. 

Do not implement anything yet - Please answer all the questions I've posed in here and also propose an implementation plan and possible suggestions to improve it. 


RESPONSE

Workspace
Collecting workspace information

Comparison to typical HA integrations

Similarities: will expose config entries, entities, and services wrapping helper code like custom_components.frame_art_shuffler.frame_tv.set_art_on_tv_deleteothers; can lean on HA’s DataUpdateCoordinator and service registry just like standard device integrations.
Differences: metadata and scheduling live outside Home Assistant; reliance on external metadata.json and add-on events is atypical and bypasses HA’s storage/state models.
Interface with Home Assistant

Recommended surface: one config flow per TV, create entities (likely sensor for current image, switch/binary_sensor for on/off, select/number for tags and frequency). Services remain appropriate for imperative commands: use HA service handlers calling helpers such as custom_components.frame_art_shuffler.frame_tv.set_tv_brightness, custom_components.frame_art_shuffler.frame_tv.tv_on, custom_components.frame_art_shuffler.frame_tv.tv_off.
Risks: tight coupling to synchronous helpers may block the event loop; wrap calls with hass.async_add_executor_job. Need validation when metadata or token directories go missing.
Integration with ha-config / frame-art-manager

Unable to locate metadata.json in the workspace; verify the add-on will generate it under a stable path accessible inside Home Assistant (e.g., /config/www/frame_art/metadata.json).
Plan seems viable if both integration and add-on agree on schema. Risks: race conditions when the add-on updates metadata while HA reads; consider watcher with throttling or require explicit “refresh” calls from the add-on via notify or custom event. Ensure relative paths resolve correctly inside HA’s container.
Additional design considerations

Config flow/onboarding: handle token acquisition and MAC addresses for Wake-on-LAN.
State recovery: define how entities rehydrate after HA restart if metadata timestamps are stale.
Error reporting: prefer HA’s logging + persistent notifications for failures, then mirror into add-on if needed.
Security: control write access to metadata/log files from both sides.
Logging approach

Custom log.json is non-standard; Home Assistant expects logs via logging and history via recorder/logbook. If a JSON log is required for the add-on, store it under /config/frame_art_logs/log.json and guard concurrent writes with asyncio.Lock. Consider rotating or bounding entries.
Implementation plan

Define metadata schema contract and location; add validation utilities in a new module (e.g., custom_components/frame_art_shuffler/metadata.py).
Build config flow that indexes TVs listed in metadata and lets users map to entities.
Create coordinator fetching metadata snapshots; publish entities per TV exposing attributes (current_image, update_frequency, etc.).
Register HA services that delegate to helper functions (set_art_on_tv_deleteothers, get_random_art_file, set_tv_brightness, tv_on, tv_off) via executor jobs.
Implement logging helper writing to shared JSON plus standard HA log entries.
Expose update triggers (e.g., async_handle_event) so the add-on or automations can request refreshes.
Add tests for metadata parsing, service handlers, and logging.
Document config expectations for the add-on and sample automations in README.md.
Suggested refinements

Consider HA events instead of ad-hoc JSON logging: emit frame_art_shuffler.image_displayed with context; the add-on can subscribe over WebSocket.
Allow optional HA-managed scheduling using TimePattern triggers as a fallback if the add-on is unavailable.
Cache metadata per TV to avoid full-file reads every service call.