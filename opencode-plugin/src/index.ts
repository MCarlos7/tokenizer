import { Plugin } from "@opencode/plugin"
import { spawn } from "node:child_process"

export default Plugin.define({
  id: "tokenizer",
  setup(ctx) {
    const command = typeof ctx.options.command === "string" ? ctx.options.command : "tokenizer"
    const child = spawn(command, ["start"], {
      detached: true,
      stdio: "ignore",
      windowsHide: true,
    })
    child.on("error", () => {})
    child.unref()
  },
})
