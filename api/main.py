import json
import asyncio
from fastapi.responses import StreamingResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
import asyncio
import json as json_module
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from core.types import *
from core.database import *
from core.auth import *
from core.connections import manager

from core.locks import lock_manager, write_queue
from core.context_manager import context_manager
from core.loop_detector import loop_detector
from core.quality_filter import quality_filter
from core.telemetry import telemetry

# ── Lifespan ─────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("NEXUS starting...")
    # Validate database connection
    try:
        pool = await get_db()
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        print("Database: OK")
    except Exception as e:
        print(f"Database connection failed: {e}")
        raise

    # Validate Redis connection
    try:
        r = await get_redis()
        await r.execute_command("PING")
        print("Redis: OK")
    except Exception as e:
        print(f"Redis warning: {e} — continuing anyway")

    print("NEXUS ready.")
    yield
    await close_connections()
    print("NEXUS shut down.")

app = FastAPI(title="NEXUS", description="Multi-Agent Collaboration Infrastructure", lifespan=lifespan)

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ── Auth Dependency ──────────────────────────────────────
async def get_current_agent(authorization: str = Header(...)):
    token = authorization.replace("Bearer ", "")
    agent_id = verify_token(token)
    if not agent_id:
        raise HTTPException(status_code=401, detail="Invalid token")
    pool = await get_db()
    agent = await db_get_agent(pool, agent_id)
    if not agent:
        raise HTTPException(status_code=401, detail="Agent not found")
    return dict(agent)

# ── Health ───────────────────────────────────────────────
@app.get("/health")
async def health():
    return {"status": "NEXUS is running", "version": "1.0.0"}

# ── Agent Registration ───────────────────────────────────
@app.post("/agents/register")
async def register_agent(req: AgentRegisterRequest):
    pool = await get_db()
    api_key = generate_api_key()
    key_hash = hash_api_key(api_key)

    await db_register_agent(
        pool, req.id, req.name, req.skills,
        req.description, key_hash, req.metadata or {}
    )

    token = create_token(req.id)

    await db_audit(pool, AuditEvent.AGENT_REGISTERED, req.id, None, {
        "name": req.name, "skills": req.skills
    })

    return {
        "agent_id": req.id,
        "api_key": api_key,
        "access_token": token,
        "message": f"Agent {req.name} registered in NEXUS"
    }

@app.get("/agents/{agent_id}")
async def get_agent(agent_id: str, current=Depends(get_current_agent)):
    pool = await get_db()
    agent = await db_get_agent(pool, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    a = dict(agent)
    return AgentInfo(
        id=a["id"], name=a["name"], skills=a["skills"],
        description=a["description"], status=a["status"], metadata=json.loads(a["metadata"])
    )

@app.get("/agents")
async def list_agents(skill: str | None = None, current=Depends(get_current_agent)):
    pool = await get_db()
    async with (await get_db()).acquire() as conn:
        if skill:
            agents = await conn.fetch(
                "SELECT * FROM agents WHERE $1 = ANY(skills) AND status != 'offline'", skill
            )
        else:
            agents = await conn.fetch("SELECT * FROM agents WHERE status != 'offline'")
    return [{"id": a["id"], "name": a["name"], "skills": a["skills"], "status": a["status"]} for a in agents]

# ── Room Management ──────────────────────────────────────
@app.post("/rooms")
async def create_room(req: CreateRoomRequest, current=Depends(get_current_agent)):
    pool = await get_db()
    await db_create_room(pool, req.id, req.name, req.purpose, current["id"], req.metadata or {})
    await db_audit(pool, AuditEvent.ROOM_CREATED, current["id"], req.id, {
        "name": req.name, "purpose": req.purpose
    })

    # Register room with context manager
    context_manager.register_room(req.id, req.purpose or req.name)
    # Register room with loop detector
    loop_detector.register_room(req.id)
    # Register room with quality filter
    quality_filter.register_room(req.id)
    # Start telemetry run
    telemetry.start_run(req.id, req.purpose or req.name)
    

@app.get("/rooms/{room_id}")
async def get_room(room_id: str, current=Depends(get_current_agent)):
    pool = await get_db()
    room = await db_get_room(pool, room_id)
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    members = await db_get_room_members(pool, room_id)
    r = dict(room)
    return {
        "id": r["id"], "name": r["name"], "purpose": r["purpose"],
        "status": r["status"], "created_by": r["created_by"],
        "members": [{"agent_id": m["agent_id"], "role": m["role"]} for m in members],
        "metadata": json.loads(r["metadata"])
    }

@app.post("/rooms/{room_id}/join")
async def join_room(room_id: str, role: str = "participant", current=Depends(get_current_agent)):
    pool = await get_db()
    room = await db_get_room(pool, room_id)
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    await db_add_room_member(pool, room_id, current["id"], role)
    await db_update_agent_status(pool, current["id"], AgentStatus.BUSY)
    manager.subscribe_to_room(current["id"], room_id)

    await db_audit(pool, AuditEvent.AGENT_JOINED_ROOM, current["id"], room_id, {"role": role})

    # Broadcast join to room
    await manager.broadcast_to_room(room_id, "agent_joined", {
        "agent_id": current["id"], "agent_name": current["name"], "role": role
    }, exclude=current["id"])

    return {"message": f"Joined room {room_id} as {role}"}

@app.post("/rooms/{room_id}/leave")
async def leave_room(room_id: str, current=Depends(get_current_agent)):
    pool = await get_db()
    await db_remove_room_member(pool, room_id, current["id"])
    await db_update_agent_status(pool, current["id"], AgentStatus.AVAILABLE)
    manager.unsubscribe_from_room(current["id"], room_id)

    await db_audit(pool, AuditEvent.AGENT_LEFT_ROOM, current["id"], room_id, {})
    await manager.broadcast_to_room(room_id, "agent_left", {"agent_id": current["id"]})

    return {"message": f"Left room {room_id}"}

# ── Messaging ────────────────────────────────────────────
@app.post("/rooms/{room_id}/messages")
async def post_message(room_id: str, req: PostMessageRequest, current=Depends(get_current_agent)):
    pool = await get_db()
    room = await db_get_room(pool, room_id)
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    # Clean up stale locks before writing
    await lock_manager.cleanup_stale_locks()

    # Acquire write lock for this room
    lock_resource = f"messages:{room_id}"
    acquired = await lock_manager.acquire(lock_resource, current["id"], timeout=10.0)
    if not acquired:
        raise HTTPException(status_code=429, detail="Room is busy — another agent is writing. Retry shortly.")

    try:
        await write_queue.submit_write(
            room_id,
            db_post_message,
            pool, req.id, room_id, current["id"], req.type,
            req.content, req.context_refs or [], req.confidence, req.metadata or {}
        )
        # Check for infinite loops before allowing message
        content_str = json_module.dumps(req.content)
        loop_check = loop_detector.record_message(
            room_id, current["id"], content_str, req.type
        )
        if loop_check["should_terminate"] and req.type not in ["VERDICT", "SYSTEM"]:
            await lock_manager.release(lock_resource, current["id"])
            raise HTTPException(
                status_code=429,
                detail=f"Loop detected — {loop_check['reason']}. Send a VERDICT to close the deliberation."
            )
            # Quality filter check
        room = await db_get_room(pool, room_id)
        room_context = dict(room).get("purpose") if room else None
        quality_result = quality_filter.score_message(
            content=json_module.dumps(req.content),
            msg_type=req.type,
            room_id=room_id,
            agent_id=current["id"],
            room_context=room_context,
            confidence=req.confidence
        )
        if not quality_result["allowed"]:
            await lock_manager.release(lock_resource, current["id"])
            telemetry.record_message_filtered(
                room_id, current["id"],
                quality_result["reason"],
                quality_result["score"]
            )
            raise HTTPException(
                status_code=422,
                detail=f"Message blocked by quality filter — {quality_result['reason']}. Score: {quality_result['score']}"
            )

        # Mark progress on important message types
        if req.type in ["POSITION", "CHALLENGE", "VERDICT"]:
            loop_detector.mark_progress(room_id)
        # Track message in context manager
        context_manager.add_message(room_id, {
            "id": req.id,
            "from_agent": current["id"],
            "type": req.type,
            "content": req.content,
            "confidence": req.confidence
        })

        # Auto-prune if context is blooming
        if context_manager.needs_pruning(room_id):
            prune_result = context_manager.prune(room_id)
            telemetry.record_context_pruned(
                room_id,
                prune_result["pruned"],
                prune_result["tokens_saved"]
            )
            await db_audit(pool, AuditEvent.SYSTEM, current["id"], room_id, {
                "event": "context_pruned",
                "pruned": prune_result["pruned"],
                "tokens_saved": prune_result["tokens_saved"]
            })

        # Record message in telemetry
        content_preview = json_module.dumps(req.content)[:200]
        telemetry.record_message(
            room_id, current["id"],
            req.type, content_preview,
            quality_score=quality_result["score"]
        )

        # Record verdict in telemetry
        if req.type == "VERDICT":
            telemetry.record_verdict(
                room_id, current["id"],
                confidence=req.confidence or 0.0
            )
            telemetry.complete_run(room_id, status="completed")

    finally:
        await lock_manager.release(lock_resource, current["id"])

    await db_audit(pool, AuditEvent.MESSAGE_POSTED, current["id"], room_id, {
        "message_id": req.id, "type": req.type, "confidence": req.confidence
    })

    # Broadcast to all room members
    message_data = {
        "id": req.id, "room_id": room_id, "from_agent": current["id"],
        "from_name": current["name"], "type": req.type,
        "content": req.content, "context_refs": req.context_refs or [],
        "confidence": req.confidence, "metadata": req.metadata or {}
    }
    await manager.broadcast_to_room(room_id, "message", message_data)

    return {"message_id": req.id, "status": "delivered"}

@app.get("/rooms/{room_id}/messages")
async def get_messages(room_id: str, limit: int = 100, offset: int = 0, current=Depends(get_current_agent)):
    pool = await get_db()
    messages = await db_get_room_messages(pool, room_id, limit, offset)
    return [
        {
            "id": m["id"], "from_agent": m["from_agent"], "type": m["type"],
            "content": json.loads(m["content"]), "context_refs": m["context_refs"],
            "confidence": m["confidence"], "created_at": str(m["created_at"]),
            "metadata": json.loads(m["metadata"])
        }
        for m in messages
    ]

# ── Context Store ────────────────────────────────────────
@app.post("/rooms/{room_id}/context")
async def set_context(room_id: str, entry: ContextEntry, current=Depends(get_current_agent)):
    pool = await get_db()
    entry_id = generate_id("ctx_")

    # Acquire write lock for context store
    lock_resource = f"context:{room_id}"
    acquired = await lock_manager.acquire(lock_resource, current["id"], timeout=10.0)
    if not acquired:
        raise HTTPException(status_code=429, detail="Context store is busy. Retry shortly.")

    try:
        await write_queue.submit_write(
            room_id,
            db_set_context,
            pool, entry_id, room_id, current["id"], entry.key, entry.value
        )
    finally:
        await lock_manager.release(lock_resource, current["id"])
    await db_audit(pool, AuditEvent.CONTEXT_UPDATED, current["id"], room_id, {
        "key": entry.key
    })
    await manager.broadcast_to_room(room_id, "context_updated", {
        "key": entry.key, "value": entry.value, "updated_by": current["id"]
    })
    return {"key": entry.key, "status": "stored"}

@app.get("/rooms/{room_id}/context")
async def get_context(room_id: str, key: str | None = None, current=Depends(get_current_agent)):
    pool = await get_db()
    if key:
        entry = await db_get_context(pool, room_id, key)
        if not entry:
            raise HTTPException(status_code=404, detail="Context key not found")
        return {"key": entry["key"], "value": json.loads(entry["value"]), "version": entry["version"]}
    entries = await db_get_context(pool, room_id)
    return [{"key": e["key"], "value": json.loads(e["value"]), "version": e["version"]} for e in entries]

# ── Recruitment ──────────────────────────────────────────
@app.post("/rooms/{room_id}/recruit")
async def recruit_agent(room_id: str, req: RecruitRequest, current=Depends(get_current_agent)):
    pool = await get_db()

    # Find available agents with needed skills
    members = await db_get_room_members(pool, room_id)
    current_member_ids = [m["agent_id"] for m in members]
    candidates = await db_find_agents_by_skills(pool, req.skills_needed, exclude_ids=current_member_ids)

    await db_create_recruitment(pool, req.id, room_id, current["id"], req.skills_needed, req.reason)
    await db_audit(pool, AuditEvent.RECRUITMENT_REQUESTED, current["id"], room_id, {
        "recruitment_id": req.id, "skills_needed": req.skills_needed,
        "candidates_found": len(candidates)
    })

    # Notify candidates
    notified = []
    for candidate in candidates:
        cand = dict(candidate)
        if manager.is_connected(cand["id"]):
            await manager.send_to_agent(cand["id"], "recruitment_request", {
                "recruitment_id": req.id, "room_id": room_id,
                "skills_needed": req.skills_needed, "reason": req.reason,
                "requested_by": current["id"]
            })
            notified.append(cand["id"])

    # Broadcast recruitment request to room
    await manager.broadcast_to_room(room_id, "recruitment_requested", {
        "recruitment_id": req.id, "skills_needed": req.skills_needed,
        "reason": req.reason, "candidates_notified": len(notified)
    })

    return {
        "recruitment_id": req.id,
        "candidates_found": len(candidates),
        "candidates_notified": len(notified),
        "candidates": [{"id": c["id"], "name": c["name"], "skills": c["skills"]} for c in candidates]
    }

@app.post("/recruitment/{recruitment_id}/accept")
async def accept_recruitment(recruitment_id: str, current=Depends(get_current_agent)):
    pool = await get_db()
    async with (await get_db()).acquire() as conn:
        req = await conn.fetchrow(
            "SELECT * FROM recruitment_requests WHERE id = $1", recruitment_id
        )
    if not req:
        raise HTTPException(status_code=404, detail="Recruitment request not found")

    r = dict(req)
    await db_resolve_recruitment(pool, recruitment_id, "fulfilled", current["id"])
    await db_add_room_member(pool, r["room_id"], current["id"], "participant")
    await db_update_agent_status(pool, current["id"], AgentStatus.BUSY)
    manager.subscribe_to_room(current["id"], r["room_id"])

    await db_audit(pool, AuditEvent.RECRUITMENT_FULFILLED, current["id"], r["room_id"], {
        "recruitment_id": recruitment_id
    })

    await manager.broadcast_to_room(r["room_id"], "agent_recruited", {
        "agent_id": current["id"], "agent_name": current["name"],
        "recruitment_id": recruitment_id
    })

    return {"message": f"Joined room {r['room_id']} via recruitment"}

# ── Audit ────────────────────────────────────────────────
@app.get("/audit")
async def get_audit(room_id: str | None = None, agent_id: str | None = None, limit: int = 200, current=Depends(get_current_agent)):
    pool = await get_db()
    logs = await db_get_audit_log(pool, room_id=room_id, agent_id=agent_id, limit=limit)
    return [
        {
            "id": l["id"], "event_type": l["event_type"], "agent_id": l["agent_id"],
            "room_id": l["room_id"], "payload": json.loads(l["payload"]),
            "created_at": str(l["created_at"])
        }
        for l in logs
    ]

    # ── Context Stats ─────────────────────────────────────────
@app.get("/rooms/{room_id}/context/stats")
async def get_context_stats(room_id: str, current=Depends(get_current_agent)):
    return context_manager.get_stats(room_id)

@app.get("/rooms/{room_id}/context/savings")
async def get_token_savings(room_id: str, current=Depends(get_current_agent)):
    return context_manager.get_token_savings_report(room_id)

# ── Loop Detection Stats ──────────────────────────────────
@app.get("/rooms/{room_id}/loops")
async def get_loop_stats(room_id: str, current=Depends(get_current_agent)):
    return loop_detector.get_stats(room_id)

@app.get("/system/loops")
async def get_system_loop_stats(current=Depends(get_current_agent)):
    return loop_detector.get_system_stats()

# ── Lock Status ──────────────────────────────────────────
@app.get("/system/locks")
async def get_lock_status(current=Depends(get_current_agent)):
    return lock_manager.get_status()

# ── Quality Filter Stats ──────────────────────────────────
@app.get("/rooms/{room_id}/quality")
async def get_quality_stats(room_id: str, current=Depends(get_current_agent)):
    return quality_filter.get_room_stats(room_id)

# ── Telemetry ─────────────────────────────────────────────
@app.get("/telemetry/runs")
async def get_all_runs(current=Depends(get_current_agent)):
    return telemetry.get_all_runs()

@app.get("/telemetry/runs/{run_id}")
async def get_run(run_id: str, current=Depends(get_current_agent)):
    summary = telemetry.get_run_summary(run_id)
    if not summary:
        raise HTTPException(status_code=404, detail="Run not found")
    return summary

@app.get("/rooms/{room_id}/telemetry")
async def get_room_telemetry(room_id: str, current=Depends(get_current_agent)):
    summary = telemetry.get_room_run_summary(room_id)
    if not summary:
        raise HTTPException(status_code=404, detail="No telemetry for this room")
    return summary

@app.get("/telemetry/runs/{run_id}/replay")
async def get_run_replay(run_id: str, current=Depends(get_current_agent)):
    replay = telemetry.get_replay(run_id)
    if not replay:
        raise HTTPException(status_code=404, detail="Run not found")
    return replay

# ── WebSocket ────────────────────────────────────────────
@app.websocket("/ws/{agent_id}")
async def websocket_endpoint(websocket: WebSocket, agent_id: str, token: str):
    verified_id = verify_token(token)
    if verified_id != agent_id:
        await websocket.close(code=4001)
        return

    pool = await get_db()
    agent = await db_get_agent(pool, agent_id)
    if not agent:
        await websocket.close(code=4004)
        return

    await manager.connect(agent_id, websocket)
    await db_update_agent_status(pool, agent_id, AgentStatus.AVAILABLE)
    await db_audit(pool, AuditEvent.AGENT_CONNECTED, agent_id, None, {})

    try:
        await manager.send_to_agent(agent_id, "connected", {
            "message": f"Connected to NEXUS as {dict(agent)['name']}",
            "agent_id": agent_id
        })
        while True:
            # Keep connection alive, receive pings
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
                await db_update_agent_status(pool, agent_id, AgentStatus.AVAILABLE)

    except WebSocketDisconnect:
        manager.disconnect(agent_id)
        await db_update_agent_status(pool, agent_id, AgentStatus.OFFLINE)
        await db_audit(pool, AuditEvent.AGENT_DISCONNECTED, agent_id, None, {})
# ── Dashboard ────────────────────────────────────────────
@app.get("/verdict")
async def dashboard():
    with open("verdict/dashboard.html", "r", encoding="utf-8") as f:
        return HTMLResponse(f.read())

# ── Verdict Streaming Endpoint ───────────────────────────
@app.post("/verdict/run")
async def run_verdict_endpoint(request: dict):
    from verdict.ingest import ingest
    from verdict.agents import (
        IntakeAgent, ContextIntegrityAgent, RecruiterAgent,
        SpecialistAgent, DevilsAdvocateAgent, JudgeAgent
    )
    import secrets

    raw_input = request.get("input", "")

    async def stream():
        try:
            agent_count = 0

            case_input = await ingest(raw_input)

            # Intake
            intake = IntakeAgent()
            await intake.register()
            agent_count += 1
            yield f"data: {json_module.dumps({'type':'agent_registered','name':'Intake Agent','count':agent_count})}\n\n"
            summary = intake.analyze(case_input)
            yield f"data: {json_module.dumps({'type':'case_summary','content':summary['raw']})}\n\n"

            # Context Integrity
            ctx = ContextIntegrityAgent()
            await ctx.register()
            agent_count += 1
            yield f"data: {json_module.dumps({'type':'agent_registered','name':'Context Integrity Agent','count':agent_count})}\n\n"
            try:
                integrity = ctx.assess(summary['raw'])
                yield f"data: {json_module.dumps({'type':'integrity','content':integrity['assessment']})}\n\n"
            except Exception as e:
                yield f"data: {json_module.dumps({'type':'integrity','content':'Context integrity check unavailable.'})}\n\n"

            # Room
            room_id = f"verdict_{secrets.token_hex(6)}"
            recruiter = RecruiterAgent()
            await recruiter.register()
            agent_count += 1
            yield f"data: {json_module.dumps({'type':'agent_registered','name':'Recruiter Agent','count':agent_count})}\n\n"
            await recruiter.nexus.create_room(room_id, "VERDICT", case_input[:200])
            await recruiter.nexus.join_room(room_id, role="recruiter")

            # Recruit
            skills = recruiter.decide_specialists(summary['raw'])
            yield f"data: {json_module.dumps({'type':'specialists','skills':skills[:3]})}\n\n"

            specialists = []
            for skill in skills[:3]:
                try:
                    s = SpecialistAgent(skill)
                    await s.register()
                    await s.nexus.join_room(room_id, role="participant")
                    specialists.append(s)
                    agent_count += 1
                    yield f"data: {json_module.dumps({'type':'agent_registered','name':s.name,'count':agent_count})}\n\n"
                except Exception as e:
                    yield f"data: {json_module.dumps({'type':'info','content':f'Could not recruit {skill} specialist'})}\n\n"

            if not specialists:
                yield f"data: {json_module.dumps({'type':'error','content':'No specialists could be recruited'})}\n\n"
                return

            # Positions
            positions = []
            for s in specialists:
                try:
                    pos = s.form_position(summary['raw'])
                    positions.append(pos)
                    await s.nexus.post(room_id, "POSITION", {"argument": pos['position']}, confidence=0.8)
                    yield f"data: {json_module.dumps({'type':'POSITION','agent':s.name,'content':pos['position']})}\n\n"
                except Exception as e:
                    yield f"data: {json_module.dumps({'type':'info','content':f'{s.name} position failed'})}\n\n"

            # Devil's Advocate
            challenge = None
            try:
                advocate = DevilsAdvocateAgent()
                await advocate.register()
                agent_count += 1
                yield f"data: {json_module.dumps({'type':'agent_registered','name':'Devils Advocate','count':agent_count})}\n\n"
                consensus = "\n".join([p['position'] for p in positions])
                challenge = advocate.challenge(consensus, summary['raw'])
                await advocate.nexus.post(room_id, "CHALLENGE", {"challenge": challenge['challenge']}, confidence=0.9)
                yield f"data: {json_module.dumps({'type':'CHALLENGE','agent':'Devils Advocate','content':challenge['challenge']})}\n\n"
            except Exception as e:
                yield f"data: {json_module.dumps({'type':'info','content':'Devils Advocate unavailable'})}\n\n"

            # Responses
            if challenge:
                for s, pos in zip(specialists, positions):
                    try:
                        resp = s.respond_to_challenge(pos['position'], challenge['challenge'])
                        await s.nexus.post(room_id, "RESPONSE", {"response": resp['response']}, confidence=0.75)
                        yield f"data: {json_module.dumps({'type':'RESPONSE','agent':s.name,'content':resp['response']})}\n\n"
                    except Exception as e:
                        yield f"data: {json_module.dumps({'type':'info','content':f'{s.name} response failed'})}\n\n"

            # Judge
            try:
                judge = JudgeAgent()
                await judge.register()
                agent_count += 1
                yield f"data: {json_module.dumps({'type':'agent_registered','name':'Judge Agent','count':agent_count})}\n\n"

                debate_log = "\n\n".join(
                    [f"[{p['specialty'].upper()} POSITION]: {p['position']}" for p in positions] +
                    ([f"[DEVIL'S ADVOCATE]: {challenge['challenge']}"] if challenge else [])
                )
                verdict = judge.deliver_verdict(summary['raw'], debate_log)
                await judge.nexus.post(room_id, "VERDICT", {"verdict": verdict['verdict']}, confidence=0.9)

                audit = await recruiter.nexus.get_audit(room_id=room_id)
                yield f"data: {json_module.dumps({'type':'VERDICT','agent':'Judge','content':verdict['verdict'],'audit_events':len(audit)})}\n\n"

            except Exception as e:
                yield f"data: {json_module.dumps({'type':'error','content':f'Judge failed: {str(e)}'})}\n\n"

        except Exception as e:
            yield f"data: {json_module.dumps({'type':'error','content':str(e)})}\n\n"

    return StreamingResponse(
    stream(),
    media_type="text/event-stream",
    headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
        "Connection": "keep-alive"
    }
)

@app.post("/verdict/run/sync")
async def run_verdict_sync(request: dict):
    from verdict.ingest import ingest
    from verdict.runner import run_verdict
    case_input = await ingest(request.get("input", ""))
    result = await run_verdict(case_input)
    return result
