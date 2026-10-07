// Workspace description: "<skill> · <state> · <detail>".
// split only splits on a single character, so split on "·" and compare with contains/hasPrefix.
func descParts(_ w) -> [String] {
  if let descriptionText = w.description {
    return descriptionText.split(separator: "·")
  }
  return []
}

func skillOf(_ w) -> String {
  let skillParts = descParts(w)
  if skillParts.count < 2 { return "" }
  if skillParts[0].hasPrefix("issue-chain") { return "issue-chain" }
  if skillParts[0].hasPrefix("planning") { return "planning" }
  if skillParts[0].hasPrefix("grilling") { return "grilling" }
  return ""
}

func stateOf(_ w) -> String {
  let stateParts = descParts(w)
  if stateParts.count < 2 { return "" }
  let stateText = stateParts[1]
  if stateText.contains("hitl") { return "hitl" }
  if stateText.contains("blocked") { return "blocked" }
  if stateText.contains("waiting") { return "waiting" }
  if stateText.contains("done") { return "done" }
  if stateText.contains("halted") { return "halted" }
  return "running"
}

func detailOf(_ w) -> String {
  let detailParts = descParts(w)
  return detailParts.count >= 3 ? detailParts[2] : ""
}

func skillColor(_ s) -> String {
  if s == "issue-chain" { return "#0a84ff" }
  if s == "planning" { return "#af52de" }
  if s == "grilling" { return "#ff9500" }
  return "#8e8e93"
}

// Check missing fields with if let only; comparing with nil does not work for absent keys.
func agentCount(_ w, _ status) -> Int {
  if let list = w.agents {
    return list.filter { $0.status == status }.count
  }
  return 0
}

func laneOf(_ w) -> String {
  if skillOf(w) == "" {
    if agentCount(w, "working") > 0 || agentCount(w, "needs_input") > 0 { return "agents" }
    return "idle"
  }
  let laneState = stateOf(w)
  if laneState == "hitl" || laneState == "blocked" || laneState == "waiting" { return "wait" }
  if laneState == "done" || laneState == "halted" { return "done" }
  return "run"
}

func projectOf(_ w) -> String {
  let segs = w.directory.split(separator: "/")
  return segs.count > 0 ? segs.last : w.title
}

func agoText(_ at) -> String {
  if at <= 0 { return "" }
  let mins = (clock.epoch - at) / 60
  if mins < 1 { return "now" }
  if mins < 60 { return "\(Int(mins))m" }
  if mins < 1440 { return "\(Int(mins / 60))h" }
  return "\(Int(mins / 1440))d"
}

func agoLabel(_ w) -> String {
  if let t = w.latestAt { return agoText(t) }
  return ""
}

func agentSummary(_ w) -> String {
  let nWork = agentCount(w, "working")
  let nInput = agentCount(w, "needs_input")
  if nWork > 0 && nInput > 0 { return "\(nWork) working · \(nInput) at prompt" }
  if nWork > 0 { return "\(nWork) working" }
  if nInput > 0 { return "\(nInput) at prompt" }
  return ""
}

func laneHeader(_ icon, _ name, _ count, _ tint) -> some View {
  HStack(spacing: 6) {
    Image(systemName: icon).font(.system(size: 11)).foregroundColor(tint)
    Text(name).font(.system(size: 11)).fontWeight(.semibold).textCase(.uppercase).foregroundColor(tint)
    Text("\(count)").font(.system(size: 10, design: .monospaced)).foregroundColor(tint)
      .padding(3)
      .background { Capsule().foregroundColor(tint).opacity(0.18) }
    Spacer()
  }
  .padding(4)
}

func card(_ w) -> some View {
  Button(action: { cmux("workspace.select", workspace_id: w.id) }) {
    VStack(alignment: .leading, spacing: 4) {
      HStack(spacing: 6) {
        Text(skillOf(w)).font(.system(size: 10)).fontWeight(.semibold)
          .foregroundColor(skillColor(skillOf(w)))
          .padding(3)
          .background { Capsule().foregroundColor(skillColor(skillOf(w))).opacity(0.15) }
        Text(projectOf(w)).font(.system(size: 12)).fontWeight(.semibold).lineLimit(1)
        Spacer()
        Text(agoLabel(w)).font(.system(size: 10, design: .monospaced)).foregroundColor(.secondary)
      }
      if let pr = w.progress {
        ProgressView(value: pr.value).tint(skillColor(skillOf(w)))
        if let lbl = pr.label {
          Text(lbl).font(.system(size: 11)).lineLimit(1)
        }
      }
      if detailOf(w) != "" {
        Text(detailOf(w)).font(.caption).foregroundColor(.secondary).lineLimit(2)
      }
      if agentSummary(w) != "" {
        Text(agentSummary(w)).font(.system(size: 10)).foregroundColor(.secondary)
      }
    }
    .padding(8)
    .background { RoundedRectangle(cornerRadius: 8).foregroundColor(.secondary).opacity(0.08) }
  }
}

func agentRow(_ w) -> some View {
  Button(action: { cmux("workspace.select", workspace_id: w.id) }) {
    HStack(spacing: 6) {
      Circle().frame(width: 6, height: 6).foregroundColor(agentCount(w, "working") > 0 ? "#34c759" : "#8e8e93")
      Text(projectOf(w)).font(.system(size: 11)).lineLimit(1)
      Spacer()
      Text(agentSummary(w)).font(.system(size: 10)).foregroundColor(.secondary)
      Text(agoLabel(w)).font(.system(size: 10, design: .monospaced)).foregroundColor(.secondary)
    }
    .padding(3)
  }
}

VStack(alignment: .leading, spacing: 6) {
  HStack {
    Text("Orchestrator runs").font(.headline)
    Spacer()
    Text(clock.time).font(.system(size: 10, design: .monospaced)).foregroundColor(.secondary)
  }
  Divider()
  let laneWait = workspaces.filter { laneOf($0) == "wait" }
  let laneRun = workspaces.filter { laneOf($0) == "run" }
  let laneDone = workspaces.filter { laneOf($0) == "done" }
  let laneAgents = workspaces.filter { laneOf($0) == "agents" }
  let laneIdle = workspaces.filter { laneOf($0) == "idle" }
  laneHeader("exclamationmark.circle.fill", "Needs you", laneWait.count, "#ff3b30")
  ForEach(laneWait) { w in card(w) }
  laneHeader("play.circle.fill", "Running", laneRun.count, "#0a84ff")
  ForEach(laneRun) { w in card(w) }
  laneHeader("checkmark.circle.fill", "Done", laneDone.count, "#34c759")
  ForEach(laneDone) { w in card(w) }
  Divider()
  laneHeader("terminal.fill", "Sessions without run", laneAgents.count, "#8e8e93")
  ForEach(laneAgents) { w in agentRow(w) }
  Text("\(laneIdle.count) workspaces without agent").font(.system(size: 10)).foregroundColor(.secondary).padding(4)
}
.padding(10)
