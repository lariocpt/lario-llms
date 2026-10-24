import type { Context } from "@opencode/plugin/promise/plugin"
import { Runs } from "./runs.js"

const providers = new Set(["geekom", "geekom7900xt", "rtx5080", "arcB70"])

export default {
  id: "lario.fixed-model-identity",
  async setup(ctx: Context) {
    const client = String(ctx.options.client || "unregistered")
    const instance = crypto.randomUUID()
    const runs = new Runs(instance)
    await ctx.session.hook("prompt", async (event) => {
      // OpenCode provides a readonly message ID at admission. It is stable on
      // transport retries and different for a later explicit user turn.
      const run = String(event.messageID || crypto.randomUUID())
      runs.begin(event.sessionID, run)
      await ctx.storage.set(`run:${event.sessionID}`, run)
    })
    await ctx.session.hook("http.request", async (event) => {
      if (!providers.has(event.model.providerID)) return
      const run = runs.current.get(event.sessionID) || await ctx.storage.get(`run:${event.sessionID}`)
      if (typeof run === 'string') runs.begin(event.sessionID, run)
      event.request.headers.set("X-Lario-Client", client)
      event.request.headers.set("X-Lario-Session", event.sessionID)
      const session = await ctx.session.get({ sessionID:event.sessionID })
      event.request.headers.set("X-Lario-Title", encodeURIComponent(session.title || ""))
      // Background title/generate requests can overlap a later user turn.
      // They carry session/kind identity, but cannot authorize cancelling that
      // later turn merely because they share its conversation.
      if (typeof run === "string" && ["primary","compaction"].includes(event.kind))
        event.request.headers.set("X-Lario-Run", run)
      event.request.headers.set("X-Lario-Instance", instance)
      event.request.headers.set("X-Lario-Location", ctx.location.directory)
      event.request.headers.set("X-Lario-Kind", event.kind)
    })
    await ctx.session.hook("retry", (event) => {
      if ([409, 423].includes(event.error.status) || runs.cancelled.has(runs.current.get(event.sessionID))) event.decision = { retry: false }
    })
    const registration = await ctx.rpc.register({
      id:'lario-model-control', events:{}, methods:{
        status:{input:{type:'object',additionalProperties:false},output:{type:'object'}},
        cancel:{input:{type:'object',properties:{session_id:{type:'string'},run_id:{type:'string'},instance_id:{type:'string'}},
          required:['session_id','run_id','instance_id'],additionalProperties:false},output:{type:'object'}},
      },
    }, {
      status:async()=>({client,instance_id:instance,version:1}),
      cancel:async(input)=>runs.cancel(input, sessionID=>ctx.session.interrupt({sessionID,resume:false})),
    })
    return ()=>registration.dispose()
  },
}
