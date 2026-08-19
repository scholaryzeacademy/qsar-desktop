import ReactDOM from "react-dom/client";
import App from "./App";
import "./index.css";

// No StrictMode: the 3Dmol.js integrations (BindingSiteModal, PoseViewer) are
// imperative WebGL code that isn't safe under StrictMode's dev-only
// mount->unmount->remount double-invoke — it doubles up viewer creation/
// teardown for no benefit here.
ReactDOM.createRoot(document.getElementById("root")!).render(<App />);
