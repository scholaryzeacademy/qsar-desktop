import { useState } from "react";
import { AppDataProvider } from "./lib/AppDataContext";
import { Shell, type TabId } from "./components/Shell";
import { ScreenTab } from "./tabs/ScreenTab";
import { PredictTab } from "./tabs/PredictTab";
import { AdmetTab } from "./tabs/AdmetTab";
import { CompareTab } from "./tabs/CompareTab";
import { DockingTab } from "./tabs/DockingTab";
import { TargetInfoTab } from "./tabs/TargetInfoTab";
import { DownloadsTab } from "./tabs/DownloadsTab";

function initialTab(): TabId {
  const h = window.location.hash.replace("#", "");
  if (["screen", "predict", "admet", "compare", "docking", "target", "downloads"].includes(h)) return h as TabId;
  return "screen";
}

export default function App() {
  const [tab, setTab] = useState<TabId>(initialTab);

  const setTabAndHash = (t: TabId) => {
    setTab(t);
    window.location.hash = t;
  };

  return (
    <AppDataProvider>
      <Shell tab={tab} onTab={setTabAndHash}>
        {/* All tabs stay mounted so in-progress input/results survive
            switching between them, matching the original single-page app's
            display:none tab toggling. */}
        <div className={tab === "screen" ? "" : "hidden"}>
          <ScreenTab />
        </div>
        <div className={tab === "predict" ? "" : "hidden"}>
          <PredictTab />
        </div>
        <div className={tab === "admet" ? "" : "hidden"}>
          <AdmetTab />
        </div>
        <div className={tab === "compare" ? "" : "hidden"}>
          <CompareTab />
        </div>
        <div className={tab === "docking" ? "" : "hidden"}>
          <DockingTab />
        </div>
        <div className={tab === "target" ? "" : "hidden"}>
          <TargetInfoTab />
        </div>
        <div className={tab === "downloads" ? "" : "hidden"}>
          <DownloadsTab />
        </div>
      </Shell>
    </AppDataProvider>
  );
}
