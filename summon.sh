#!/bin/bash
#
# summon.sh (kdotool)
#
# Launches an app or focuses running. Brings to active display.

DEBUG=false
LOG_FILE="/tmp/summon.log"
CLASS_NAME="$1"

debug() {
    if [ "$DEBUG" = true ]; then
        echo "[DEBUG] $1" >> $LOG_FILE
    fi
}

debug "Script started for class: '$CLASS_NAME'"

declare -A LAUNCH_MAP
LAUNCH_MAP["brave-browser"]="brave &"
LAUNCH_MAP["steam"]="steam &"
LAUNCH_MAP["spotify"]="spotify &"
LAUNCH_MAP["org.kde.konsole"]="konsole &"
LAUNCH_MAP["systemsettings"]="systemsettings &"
debug "Application map loaded."

if [ -z "$CLASS_NAME" ]; then
    echo "Usage: $0 \"resourceClass\"" >&2
    debug "Error: No resourceClass argument provided. Exiting."
    exit 1
fi
debug "Argument check passed."

if ! [[ -v LAUNCH_MAP[$CLASS_NAME] ]]; then
    echo "Error: Unknown resourceClass '$CLASS_NAME'." >&2
    echo "Please add it to the 'APPLICATION MAP' in $0" >&2
    debug "Error: resourceClass '$CLASS_NAME' not found in map. Exiting."
    exit 1
fi
debug "resourceClass '$CLASS_NAME' found in map."

if ! command -v kdotool &> /dev/null; then
    echo "Error: kdotool is not installed. Please install it from the AUR." >&2
    debug "Error: kdotool command not found. Exiting."
    exit 1
fi
debug "kdotool command found at: $(which kdotool)"

LAUNCH_COMMAND=${LAUNCH_MAP[$CLASS_NAME]}
debug "Launch command set to: $LAUNCH_COMMAND"

CURRENT_DISPLAY=$(qdbus6 org.kde.KWin /KWin activeOutputName)
debug "Current display: $CURRENT_DISPLAY"

debug "Searching for windows with class: $CLASS_NAME"
POSSIBLE_IDS=$(kdotool search --class "$CLASS_NAME")

SAME_DISPLAY_ID=""
OTHER_DISPLAY_ID=""

if [ -n "$POSSIBLE_IDS" ]; then
    readarray -t ID_ARRAY <<< "$POSSIBLE_IDS"
    debug "Search returned ${#ID_ARRAY[@]} IDs: ${ID_ARRAY[*]}"
    
    for id in "${ID_ARRAY[@]}"; do
        debug "Inspecting ID: $id"
        ACTUAL_CLASS=$(kdotool getwindowclassname "$id")
        debug "  -> Actual class: '$ACTUAL_CLASS'"
        
        if [ "$ACTUAL_CLASS" = "$CLASS_NAME" ]; then
            debug "  -> Matched. Checking display..."
            
            WIN_X=$(kdotool getwindowgeometry "$id" | grep -oP 'Position: \K\d+' | head -1)
            debug "  -> Window x: $WIN_X"
            
            # HDMI-A-1: x=0 to x=1920
            # DP-2: x=1920 to x=3840
            if [ "$WIN_X" -lt 1920 ]; then
                WIN_DISPLAY="HDMI-A-1"
            else
                WIN_DISPLAY="DP-2"
            fi
            debug "  -> Window display: $WIN_DISPLAY"
            
            if [ "$WIN_DISPLAY" = "$CURRENT_DISPLAY" ]; then
                SAME_DISPLAY_ID="$id"
                debug "  -> Found on active display"
                break  # Prioritize same display
            elif [ -z "$OTHER_DISPLAY_ID" ]; then
                OTHER_DISPLAY_ID="$id"
                debug "  -> Found on other display"
            fi
        fi
    done
fi

if [ -n "$SAME_DISPLAY_ID" ]; then
    debug "Action: Activating window: $SAME_DISPLAY_ID"
    kdotool windowactivate "$SAME_DISPLAY_ID"
elif [ -n "$OTHER_DISPLAY_ID" ]; then
    debug "Action: Moving and activating window: $OTHER_DISPLAY_ID"
    # Move window to current display
    if [ "$CURRENT_DISPLAY" = "HDMI-A-1" ]; then
        kdotool windowmove "$OTHER_DISPLAY_ID" 100 100
    else
        kdotool windowmove "$OTHER_DISPLAY_ID" 2000 100
    fi
    kdotool windowactivate "$OTHER_DISPLAY_ID"
else
    debug "Action: No matching window found. Executing launch command..."
    eval "$LAUNCH_COMMAND"
fi

debug "Script finished."
