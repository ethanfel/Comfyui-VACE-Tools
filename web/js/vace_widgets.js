import { app } from "../../scripts/app.js";

app.registerExtension({
    name: "VACE.SourcePrep.SmartDisplay",
    nodeCreated(node) {
        if (node.comfyClass !== "VACESourcePrep") return;

        const modeWidget = node.widgets.find(w => w.name === "mode");
        if (!modeWidget) return;

        const VISIBILITY = {
            "End Extend":           { split_index: false, input_left: true,  input_right: false, edge_frames: false },
            "Pre Extend":           { split_index: false, input_left: false, input_right: true,  edge_frames: false },
            "Middle Extend":        { split_index: true,  input_left: true,  input_right: true,  edge_frames: false },
            "Edge Extend":          { split_index: false, input_left: true,  input_right: true,  edge_frames: true  },
            "Join Extend":          { split_index: false, input_left: true,  input_right: true,  edge_frames: true  },
            "Bidirectional Extend": { split_index: true,  input_left: true,  input_right: false, edge_frames: false },
            "Frame Interpolation":  { split_index: true,  input_left: false, input_right: false, edge_frames: false },
            "Replace/Inpaint":      { split_index: true,  input_left: true,  input_right: true,  edge_frames: true  },
            "Video Inpaint":        { split_index: false, input_left: false, input_right: false, edge_frames: false },
            "Keyframe":             { split_index: false, input_left: false, input_right: false, edge_frames: false },
        };

        function toggleWidget(widget, show) {
            if (!widget) return;
            if (!widget._origType) widget._origType = widget.type;
            widget.type = show ? widget._origType : "hidden";
        }

        function updateVisibility(mode) {
            const vis = VISIBILITY[mode];
            if (!vis) return;
            for (const [name, show] of Object.entries(vis)) {
                toggleWidget(node.widgets.find(w => w.name === name), show);
            }
            node.setSize(node.computeSize());
            app.graph.setDirtyCanvas(true);
        }

        // Hook mode widget value setter to catch both UI and programmatic changes
        const descriptor = Object.getOwnPropertyDescriptor(modeWidget, "value") ||
            { configurable: true };
        const hasCustomAccessor = !!descriptor.get;

        if (!hasCustomAccessor) {
            let _value = modeWidget.value;
            Object.defineProperty(modeWidget, "value", {
                get() { return _value; },
                set(v) {
                    _value = v;
                    updateVisibility(v);
                },
                configurable: true,
            });
        } else {
            const origGet = descriptor.get;
            const origSet = descriptor.set;
            Object.defineProperty(modeWidget, "value", {
                get() { return origGet.call(this); },
                set(v) {
                    origSet.call(this, v);
                    updateVisibility(v);
                },
                configurable: true,
            });
        }

        // Also hook callback for dropdown selection events
        const origCallback = modeWidget.callback;
        modeWidget.callback = function(value) {
            updateVisibility(value);
            if (origCallback) origCallback.call(this, value);
        };

        // Initial update
        updateVisibility(modeWidget.value);
    },
});

app.registerExtension({
    name: "VACE.MergeBack.SmartDisplay",
    nodeCreated(node) {
        if (node.comfyClass !== "VACEMergeBack") return;

        const methodWidget = node.widgets.find(w => w.name === "blend_method");
        if (!methodWidget) return;

        function toggleWidget(widget, show) {
            if (!widget) return;
            if (!widget._origType) widget._origType = widget.type;
            widget.type = show ? widget._origType : "hidden";
        }

        function updateVisibility(method) {
            const showBlend = method !== "none";
            const showOf = method === "optical_flow";
            toggleWidget(node.widgets.find(w => w.name === "blend_frames"), showBlend);
            toggleWidget(node.widgets.find(w => w.name === "of_preset"), showOf);
            node.setSize(node.computeSize());
            app.graph.setDirtyCanvas(true);
        }

        const descriptor = Object.getOwnPropertyDescriptor(methodWidget, "value") ||
            { configurable: true };
        const hasCustomAccessor = !!descriptor.get;

        if (!hasCustomAccessor) {
            let _value = methodWidget.value;
            Object.defineProperty(methodWidget, "value", {
                get() { return _value; },
                set(v) {
                    _value = v;
                    updateVisibility(v);
                },
                configurable: true,
            });
        } else {
            const origGet = descriptor.get;
            const origSet = descriptor.set;
            Object.defineProperty(methodWidget, "value", {
                get() { return origGet.call(this); },
                set(v) {
                    origSet.call(this, v);
                    updateVisibility(v);
                },
                configurable: true,
            });
        }

        const origCallback = methodWidget.callback;
        methodWidget.callback = function(value) {
            updateVisibility(value);
            if (origCallback) origCallback.call(this, value);
        };

        updateVisibility(methodWidget.value);
    },
});
