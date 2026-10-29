#!/usr/bin/env python3
r"""_llm.py — shared external-LLM curation engine (zero Claude tokens).

Consolidates the proven gauntlet: Groq pool (key rotation + Cloudflare browser-UA
fix, see technique_output/70-pitfalls/cloudflare-ja3-fingerprinting.md) with a
Gemini fallback, distillation, an adversarial source-grounded gate, placement, and
promotion. Imported by ext-digest.py / fetch-links.py / auto-curate.py.

Keys: $CLAUDE_SHARED\_secrets\api-matrix.json (gitignored).
"""
import os,sys,json,re,socket,urllib.request,urllib.error,time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # co-located engines (_paths)
from _paths import SKILL, INBOX, TECHNIQUE_OUTPUT, API_MATRIX, ENGINES
from _free_api_supervisor import CircuitStore

HUB=SKILL  # kept for back-compat (consumers may use _llm.HUB)
I=INBOX
O=TECHNIQUE_OUTPUT
DRAFTS=os.path.join(INBOX,"_ai_drafts")
MATRIX=API_MATRIX  # see $CLAUDE_SHARED\_secrets\api-matrix.json
UA=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
FOLDERS=["10-foundations","20-claude-code","30-agent-sdk","40-mcp","50-techniques",
         "60-projects","70-pitfalls","99-sources"]

SYS_DIGEST=("You distill raw notes into ONE dense canonical technique doc for a Claude "
"knowledge base. Output STRICT markdown only, no preamble. Format:\n"
"---\nlast_updated: 2026-06-04\nversion: 1\n---\n\n# <Imperative title>\n\n"
"> <=40-word TL;DR (becomes the index entry - dense + keyword-rich).\n\n"
"## When to use\n- ...\n\n## The pattern\n<core mechanism, code if present>\n\n"
"## Pitfalls\n- ...\n\n## Sources\n- <verbatim source path/url from the input>\n\n"
"RULES: maximize effect-per-token - terse, no filler, no restating the prompt. Add NO "
"technical specifics (commands/versions/numbers/mechanisms) not present in the input. "
"If the input has no reusable technique, output exactly: SKIP")

_SECRETISH=(re.compile(r"(?i)([?&](?:key|api_key|token)=)[^&\s'\"]+"),       # ?key=... in a URL
            re.compile(r"[A-Za-z0-9]{2,}\*{3,}[A-Za-z0-9]{2,}"),                 # provider-masked key echo
            re.compile(r"(?<![A-Za-z0-9])[A-Za-z0-9_\-]{28,}(?![A-Za-z0-9])"))   # bare long token / id
def redact(text):
    """Error text safe for the health file and logs: no key, masked key echo, or long opaque token survives."""
    s=str(text or "")
    s=_SECRETISH[0].sub(r"\1<redacted>",s)
    for rx in _SECRETISH[1:]: s=rx.sub("<redacted>",s)
    return s

def load_matrix():
    if not os.path.exists(MATRIX): return None
    return json.loads(open(MATRIX,encoding="utf-8-sig").read())

class Pool:
    """Rotating Groq key pool + Gemini fallback. All calls send a browser UA."""
    def __init__(self,m=None):
        m=m or load_matrix()
        if not m: raise RuntimeError(f"no api-matrix at {MATRIX}")
        self.circuits=CircuitStore()
        self.groq=[k["key"] for k in m["keys"] if k["provider"]=="groq" and k["status"]=="ok"]
        self.gemkeys=[k["key"] for k in m["keys"] if k["provider"]=="gemini" and k["status"]=="ok"]
        self.hfkeys=[k["key"] for k in m["keys"] if k["provider"]=="huggingface" and k["status"]=="ok"]
        self.cerebras=[(k["key"],k.get("model","gpt-oss-120b")) for k in m["keys"] if k["provider"]=="cerebras" and k["status"]=="ok"]
        # OpenRouter free-model BREADTH: one ToS-compliant key unlocks ALL :free models. Cross the
        # ok key(s) with the curated roster (endpoints.openrouter.models) so _oai rotates to the next
        # free model when one 429s (shared daily cap) or gets decommissioned (the :free roster churns).
        # This is legit aggregator breadth, NOT multi-account quota-stacking. Roster is data (matrix),
        # bounded to a handful so a daily-cap 429 doesn't churn dozens of models.
        # see 50-techniques/multi-provider-llm-fallback.md (KB 2026.06.09-18)
        _or_models=((m.get("endpoints",{}).get("openrouter",{}) or {}).get("models")) or ["google/gemma-4-31b-it:free"]
        # DEFENSIVE: a valid OpenRouter free id is 'vendor/model:free'. Drop malformed entries
        # (a concurrent harvester once left a phantom 'openrouter/free') so the pool never 404s on
        # garbage -> no "dying" calls from a bad roster. key-pool-tick refreshes the roster live.
        _or_models=[x for x in _or_models if isinstance(x,str) and "/" in x and x.endswith(":free")] or ["google/gemma-4-31b-it:free"]
        self.openrouter=[(k["key"],mdl) for k in m["keys"]
                         if k["provider"]=="openrouter" and k["status"]=="ok" and k.get("key")
                         for mdl in _or_models]
        self.ollama=[(None,k.get("model","qwen2.5:7b")) for k in m["keys"] if k["provider"]=="ollama" and k["status"]=="ok"]
        self.ollama_url=(m.get("endpoints",{}).get("ollama",{}) or {}).get("url","http://localhost:11434/v1/chat/completions")
        self.ollama_cpu_only=(m.get("endpoints",{}).get("ollama",{}) or {}).get("cpu_only") is True   # see _local_enabled
        # ollama model resolved only when status==ok (operator: no-local-llm-on-this-machine).
        _om=[k for k in m["keys"] if k["provider"]=="ollama" and k["status"]=="ok"]
        self.ollama_model=(_om[0].get("model") if _om else "qwen2.5:7b")
        self.gq=m["endpoints"]["groq"]; self.gem=m["endpoints"].get("gemini"); self.gi=0
        self.hf_model="meta-llama/Llama-3.1-8B-Instruct"
        # --- extra OpenAI-compatible providers: decorrelated model FAMILIES + quota pools ---
        # A provider only adds adversarial strength if its model family DIFFERS from the
        # others (decorrelated voters). sambanova/together/fireworks mostly host llama/qwen
        # = same family as groq/ollama -> they buy QUOTA, not decorrelation. mistral + nvidia
        # (deepseek) are genuinely new families. see 50-techniques/adversarial-debate-verification.md
        eps=m.get("endpoints",{})
        def _url(prov,d): return (eps.get(prov,{}) or {}).get("url",d)
        def _pool(prov,defmodel):
            return [(k["key"],self.RETIRED.get(k.get("model",defmodel),k.get("model",defmodel))) for k in m["keys"]
                    if k.get("provider")==prov and k.get("status")=="ok" and k.get("key")]
        self.mistral  =_pool("mistral","mistral-large-latest")
        self.nvidia   =_pool("nvidia-nim","deepseek-ai/deepseek-r1")
        self.sambanova=_pool("sambanova","Meta-Llama-3.3-70B-Instruct")
        self.together =_pool("together","Qwen/Qwen2.5-72B-Instruct-Turbo")
        self.fireworks=_pool("fireworks","accounts/fireworks/models/llama-v3p3-70b-instruct")
        # --- Cloudflare Workers AI: free tier (10k neurons/day), OpenAI-compatible -----------
        # environment-aware exclusion: a cf_ai key is USELESS without an account_id (the id is
        # baked into the URL PATH, not a header), so the pool stays EMPTY unless BOTH are
        # present -> it never half-enters the chain. account_id resolves from the key entry
        # first, else endpoints.cf_ai.account_id (one account for all keys). URL is templated
        # PER KEY so a future multi-account setup still works. cf hosts llama/qwen/mistral/
        # gemma -> family "llama"; this buys free QUOTA, not voter decorrelation.
        # see 50-techniques/multi-provider-llm-fallback.md (environment-aware exclusion, KB 2026.06.06-1)
        _cfacct=(eps.get("cf_ai",{}) or {}).get("account_id")
        _cftpl="https://api.cloudflare.com/client/v4/accounts/{acct}/ai/v1/chat/completions"
        self.cf_ai=[]   # list of (key, model, url) — only entries with BOTH key AND account_id
        for k in m["keys"]:
            if k.get("provider")!="cf_ai" or k.get("status")!="ok" or not k.get("key"): continue
            acct=k.get("account_id") or _cfacct
            if not acct: continue   # key present but no account_id -> excluded (env-aware)
            self.cf_ai.append((k["key"],k.get("model","@cf/meta/llama-3.1-8b-instruct"),
                               _cftpl.format(acct=acct)))
        # provider -> (url, family, keypool) for the extra OpenAI-compatible providers
        self.XPROV={
            "mistral":   (_url("mistral","https://api.mistral.ai/v1/chat/completions"),"mistral",self.mistral),
            "nvidia-nim":(_url("nvidia-nim","https://integrate.api.nvidia.com/v1/chat/completions"),"deepseek",self.nvidia),
            "sambanova": (_url("sambanova","https://api.sambanova.ai/v1/chat/completions"),"llama",self.sambanova),
            "together":  (_url("together","https://api.together.xyz/v1/chat/completions"),"qwen",self.together),
            "fireworks": (_url("fireworks","https://api.fireworks.ai/inference/v1/chat/completions"),"llama",self.fireworks),
        }
    def _groq(self,messages,jsonmode,max_tokens=3000):
        if not self.groq: return "__ERR__ no-groq"   # empty pool -> avoid %0 (see api-matrix status)
        model=self.gq["models"][0]; last=None
        for _ in range(max(1,len(self.groq))*3):     # 3 passes over the pool
            key=self.groq[self.gi%len(self.groq)]
            d={"model":model,"temperature":0.1,"max_tokens":max_tokens,"messages":messages}
            if jsonmode: d["response_format"]={"type":"json_object"}
            req=urllib.request.Request(self.gq["url"],method="POST",headers={
                "Authorization":f"Bearer {key}","Content-Type":"application/json",
                "User-Agent":UA,"Accept":"application/json"})
            try:
                r=urllib.request.urlopen(req,data=json.dumps(d).encode(),timeout=120)
                return json.loads(r.read())["choices"][0]["message"]["content"]
            except urllib.error.HTTPError as e:
                if e.code in(429,503): self.gi+=1; time.sleep(1); last=str(e.code); continue
                return f"__ERR__ groq {e.code} {redact(e.read()[:140])}"
            except Exception as e:
                # transient (SSL bad-record-mac, conn reset): rotate key + backoff, keep trying
                self.gi+=1; time.sleep(1.5); last=str(e); continue
        return f"__ERR__ groq transient ({last})"
    def _gemini(self,messages,jsonmode):
        if not self.gem or not self.gemkeys: return "__ERR__ no-gemini"
        model=self.gem["models"][0]; url=self.gem["url"].format(model=model)
        text="\n\n".join(m["content"] for m in messages)
        last="none"
        for key in self.gemkeys:
            req=urllib.request.Request(f"{url}?key={key}",method="POST",
                headers={"Content-Type":"application/json","User-Agent":UA})
            data={"contents":[{"parts":[{"text":text}]}],"generationConfig":{"temperature":0.1}}
            try:
                r=urllib.request.urlopen(req,data=json.dumps(data).encode(),timeout=120)
                return json.loads(r.read())["candidates"][0]["content"]["parts"][0]["text"]
            except urllib.error.HTTPError as e:
                last="%s %s"%(e.code,e.read()[:120]); continue   # 2026-10-27: 503 high-demand on one key -> next key
            except Exception as e:
                last=type(e).__name__; continue
        return "__ERR__ gemini-failed (%s)"%redact(last)
    def _hf(self,messages,jsonmode,max_tokens=3000):
        """HuggingFace Inference Providers router — OpenAI-compatible text fallback."""
        if not self.hfkeys: return "__ERR__ no-hf"
        d={"model":self.hf_model,"messages":messages,"max_tokens":max_tokens,"temperature":0.1}
        if jsonmode: d["response_format"]={"type":"json_object"}
        last="none"
        for key in self.hfkeys:
            req=urllib.request.Request("https://router.huggingface.co/v1/chat/completions",
                method="POST",headers={"Authorization":f"Bearer {key}","Content-Type":"application/json","User-Agent":UA})
            try:
                r=urllib.request.urlopen(req,data=json.dumps(d).encode(),timeout=90)
                return json.loads(r.read())["choices"][0]["message"]["content"]
            except urllib.error.HTTPError as e:
                last="%s %s"%(e.code,e.read()[:120]); continue
            except Exception as e:
                last=type(e).__name__; continue
        return "__ERR__ hf-failed (%s)"%redact(last)

    REASONING_FLOOR=1024
    def _oai(self,provkeys,url,messages,jsonmode,max_tokens,timeout=90):
        """Generic OpenAI-compatible call over a provider's [(key,model)] list.
        Retries transient failures (SSL bad-record-mac, conn reset, 429/503) up to 3x
        per key with backoff -- cerebras/openrouter intermittently drop large payloads on
        SSL, and a single-key pool with no retry was wrongly returning __ERR__ (the silent
        cause of distill MAP segments dropping to 0 extracts). Empty content (a reasoning-
        only reply) moves to the next key instead of burning retries.
        see 50-techniques/multi-provider-llm-fallback.md"""
        last="none"; capped=set()
        for key,model in provkeys:
            if key in capped: continue   # free-tier 429 is account-wide -> don't churn this key's other models
            d={"model":model,"messages":messages,"max_tokens":max_tokens,"temperature":0.1}
            if jsonmode: d["response_format"]={"type":"json_object"}
            if url==getattr(self,"ollama_url",None) and self._local_enabled(): d["keep_alive"]="30m"   # CPU-only local
            hdr={"Content-Type":"application/json","User-Agent":UA}
            if key: hdr["Authorization"]=f"Bearer {key}"   # local Ollama needs no auth
            widened=False
            for attempt in range(3):
                req=urllib.request.Request(url,method="POST",headers=hdr)
                try:
                    r=urllib.request.urlopen(req,data=json.dumps(d).encode(),timeout=timeout)
                    ch=json.loads(r.read())["choices"][0]
                    c=ch["message"].get("content")
                    if c: return c
                    # 2026-10-27: NVIDIA z-ai/glm-5.3-flash always thinks (chat_template_kwargs ignored); a small
                    # max_tokens is eaten by reasoning_content and content comes back null with finish=length.
                    # Widen the budget once on the same key instead of marking a healthy provider failed.
                    if ch.get("finish_reason")=="length" and not widened and d["max_tokens"]<self.REASONING_FLOOR:
                        d=dict(d,max_tokens=self.REASONING_FLOOR); widened=True; continue
                    last="empty-content"; break          # reasoning-only reply -> next key
                except urllib.error.HTTPError as e:
                    body=e.read()[:600]; last="%s %s"%(e.code,body[:120])
                    # 2026-10-27: OpenRouter's 429 "<model>:free is temporarily rate-limited upstream" is per MODEL
                    # (the same key answered on nemotron/laguna right after) -> next model, keep the key.
                    if e.code==429 and b"upstream" not in body: capped.add(key); break   # account-wide cap
                    if e.code==429: break
                    if e.code==503: time.sleep(1.0); continue # transient -> retry same model
                    break                                 # other 4xx/5xx -> next key
                except Exception as e:
                    last=type(e).__name__; time.sleep(1.0); continue   # transient SSL/conn -> retry
        return "__ERR__ oai-failed (%s)"%redact(last)

    def _cf(self,messages,jsonmode,max_tokens=3000,timeout=90):
        """Cloudflare Workers AI — OpenAI-compatible, account_id is in the URL path so keys can
        span accounts. Groups (key,model,url) triples by url and delegates each group to _oai
        (same transient-retry semantics). Empty pool (no key+account_id) -> __ERR__, never fires.
        see 50-techniques/multi-provider-llm-fallback.md (KB 2026.06.06-1)"""
        if not self.cf_ai: return "__ERR__ no-cf_ai"
        byurl={}
        for key,model,url in self.cf_ai: byurl.setdefault(url,[]).append((key,model))
        last="none"
        for url,provkeys in byurl.items():
            res=self._oai(provkeys,url,messages,jsonmode,max_tokens,timeout)
            if not res.startswith("__ERR__"): return res
            last=res
        return last if last.startswith("__ERR__") else "__ERR__ cf_ai-failed"

    # T1 free-runtime + A770 power-loss red line (2026-10-27): Ollama :11434 runs on the Intel A770 (Vulkan) on this box,
    # and A770 load steps are what tripped the power losses. The pool may never route there, whatever the matrix says.
    # Only an endpoint the matrix marks `cpu_only: true` on a port other than 11434 (e.g. the theater CPU server :11436)
    # can be enabled, and each call still needs a load_grant before it adds load.
    A770_PORTS=frozenset({11434})
    LOCAL_GRANT_W=40
    def _local_port(self):
        from urllib.parse import urlsplit
        try:
            u=urlsplit(getattr(self,"ollama_url","") or "")
            return u.hostname or "", (u.port or (443 if u.scheme=="https" else 80))
        except ValueError:
            return "", 0
    def _local_enabled(self):
        """True only when api-matrix marks ollama status==ok AND its endpoint is explicitly CPU-only off the A770 port."""
        if not getattr(self,"ollama",None) or not getattr(self,"ollama_cpu_only",False):
            return False
        host,port=self._local_port()
        return host in ("127.0.0.1","localhost","::1") and port not in self.A770_PORTS

    def _local_grant(self):
        """load_grant (ai_darkhero/tray/scripts) must approve the step; any import or grant failure = no local call."""
        try:
            sd=os.path.join(os.path.dirname(os.path.dirname(ENGINES)),"ai_darkhero","tray","scripts")
            if sd not in sys.path: sys.path.insert(0,sd)
            import load_grant
            return bool(load_grant.try_grant("pool/ollama-cpu",self.LOCAL_GRANT_W).get("ok"))
        except Exception:
            return False

    def _ollama_up(self):
        """Fast probe of the configured CPU-only endpoint (0.5s) instead of a 240s HTTP timeout."""
        if not self._local_enabled():
            return False
        host,port=self._local_port()
        try:
            with socket.create_connection((host,port), timeout=0.5):
                return True
        except OSError:
            return False

    _CLOUD_FALLBACK = ("gemini", "groq", "openrouter", "cerebras", "hf", "cf_ai",
                       "mistral", "nvidia-nim", "sambanova", "together", "fireworks")

    def cloud_fallback(self, messages, jsonmode=False, max_tokens=1500, skip=()):
        """After a pinned provider fails, try cloud peers in decorrelated order. Local ollama only if enabled."""
        skip = set(skip or ())
        avail = set(self.available_providers())
        for prov in self._CLOUD_FALLBACK:
            if prov in skip or prov not in avail:   # no credentials -> never called, never counted as a failure
                continue
            raw = self.chat_via(prov, messages, jsonmode=jsonmode, max_tokens=max_tokens)
            if not raw.startswith("__ERR__"):
                return raw, prov
        if self._ollama_up():
            raw = self.chat_via("ollama", messages, jsonmode=jsonmode, max_tokens=max_tokens)
            if not raw.startswith("__ERR__"):
                return raw, "ollama"
        return "__ERR__ cloud-fallback-exhausted", ""

    def chat(self,messages,jsonmode=False,max_tokens=3000):
        """Cloud-first fallback with persistent per-provider circuit breaking."""
        last="__ERR__ no-provider"
        for prov in ("groq","cerebras","openrouter","cf_ai","hf","gemini",
                     "mistral","nvidia-nim","sambanova","together","fireworks"):
            if prov not in self.available_providers():
                continue
            last=self.chat_via(prov,messages,jsonmode=jsonmode,max_tokens=max_tokens)
            if not last.startswith("__ERR__"):
                return last
        if self._ollama_up():
            return self.chat_via("ollama",messages,jsonmode=jsonmode,max_tokens=max_tokens)
        return last
    def available_providers(self):
        """Providers with usable credentials right now; ollama only when operator-enabled."""
        a=[]
        if self.groq: a.append("groq")
        if self.cerebras: a.append("cerebras")
        if self.openrouter: a.append("openrouter")
        if self.cf_ai: a.append("cf_ai")
        if self.hfkeys: a.append("hf")
        if self.gemkeys: a.append("gemini")
        for prov,(url,fam,keys) in self.XPROV.items():
            if keys: a.append(prov)
        if self._local_enabled():
            a.append("ollama")
        return a
    def panel(self,n=4):
        """Pick up to n adversarial voters from DISTINCT model families (decorrelated votes).
        Within a family choose the provider holding the most usable keys (quota headroom).
        Families ordered by decorrelation value: a genuinely independent judge (mistral,
        deepseek, gemini, gpt-oss) before same-as-local (qwen/llama). ollama(qwen) is the
        always-present local floor. Returns [(provider,family)].
        see 50-techniques/adversarial-debate-verification.md (KB)"""
        cands=[]
        if self.groq:       cands.append(("groq","llama",len(self.groq)))
        if self.cerebras:   cands.append(("cerebras","gpt-oss",len(self.cerebras)))
        if self.openrouter: cands.append(("openrouter","mixed-free",len(self.openrouter)))
        if self.cf_ai:      cands.append(("cf_ai","llama",len(self.cf_ai)))
        if self.hfkeys:     cands.append(("hf","llama",len(self.hfkeys)))
        if self.gemkeys:    cands.append(("gemini","gemini",len(self.gemkeys)))
        for prov,(url,fam,keys) in self.XPROV.items():
            if keys: cands.append((prov,fam,len(keys)))
        if self._local_enabled():
            cands.append(("ollama","qwen",1))
        best={}                                               # one provider per family: most keys wins
        for prov,fam,w in cands:
            if fam not in best or w>best[fam][2]: best[fam]=(prov,fam,w)
        order=["mistral","deepseek","gemini","gpt-oss","qwen","llama","mixed-free"]
        chosen=sorted(best.values(),key=lambda x:(order.index(x[1]) if x[1] in order else 99,-x[2]))
        return [(p,f) for p,f,_ in chosen[:n]]
    def panel_chat(self,messages,n=3,jsonmode=False,max_tokens=1500):
        """Adversarial multi-FAMILY vote: query up to n decorrelated providers (panel() picks one
        per distinct model family) and return [(provider,family,answer)] for those that answered
        (errors dropped). Different families = decorrelated voters; majority-vote the answers
        upstream. This is what actually buys adversarial robustness -- NOT multiple accounts of the
        same provider (same model = correlated = useless). Each provider self-heals via its own pool.
        see 50-techniques/decorrelated-adversarial-verification.md (KB 2026.09-18)"""
        out=[]
        for prov,fam in self.panel(n):
            ans=self.chat_via(prov,messages,jsonmode=jsonmode,max_tokens=max_tokens)
            if not (isinstance(ans,str) and ans.startswith("__ERR__")):
                out.append((prov,fam,ans))
        return out
    # operator 2026-10-15: bind each free model to what it is measurably good at. Labels come from the
    # 2026-10-15 probe (2 rounds x zh summary / JSON extract / arithmetic reasoning on this machine):
    #   gemini            6/6 correct, 1-3 s           -> default for summary, extraction, vision, bulk
    #   omniroute:auto/coding     5/6, 2-18 s          -> second choice for text work
    #   omniroute:auto/reasoning  reasoning 2/2, 2 s   -> first choice for reasoning only (others slow)
    #   omniroute:auto/fast 4/6 up to 70 s, auto/writing 404, nvidia-nim breaker open -> not routed
    # upstream end-of-life models -> live replacement (the matrix `model` field lives in _secrets, not edited here).
    # 2026-10-16: nvidia deepseek-v4-pro returned 410 Gone; glm-5.3-flash translated ja->zh-TW correctly (42 s).
    # 2026-10-27: mistral-large-latest answers 403 tier_not_allowed on the free tier (the key itself is valid);
    # ministral-14b-latest / ministral-8b-latest answer 200 in 0.6 s on the same key.
    RETIRED={"deepseek-ai/deepseek-v4-pro":"z-ai/glm-5.3-flash","mistral-large-latest":"ministral-14b-latest"}
    TASK_ROUTES={
        "summary":["gemini","omniroute:auto/coding"],
        # 2026-10-18 (ai_trader F1S proposal, 40-title JSON labelling): ddgw/gpt-5.4-mini 2.0/1.6/2.3 s and parsed on
        # every probe (88/120 labels agree with gemini); auto/coding and auto/reasoning answered in prose there, so
        # structured tasks take ddgw before auto/coding. auto/coding stays last: the curator probe the same night got
        # valid JSON from it in 4.2 s while ddgw answered 503 "Failed to acquire VQD token" (keyless upstream, volatile).
        # A prose answer no longer counts as success: chat_for(jsonmode=True) drops non-JSON output to the next route.
        "extract":["gemini","omniroute:ddgw/gpt-5.4-mini","omniroute:auto/coding"],
        # 2026-10-27 re-probe: auto/reasoning answered 502 (its combo picked nvidia moonshotai/kimi-k3, EOL 410 since
        # 2026-10-15), then 1.5 s, then 63.8 s -> volatile, moved last. gemini 1.3 s; nvidia glm-5.3-flash 1.2-1.9 s.
        "reasoning":["gemini","nvidia:z-ai/glm-5.3-flash","omniroute:auto/reasoning"],
        "bulk":["gemini","omniroute:ddgw/gpt-5.4-mini","omniroute:auto/coding"],
        # 2026-10-16 ja->zh-TW probe: gemini 1.1 s, auto/reasoning 1.8 s, ddgw/gpt-5.4-mini 3.6 s, cfp glm-5.2 11 s,
        # nvidia glm-5.3-flash 42 s (all correct). auto/chat took 104 s -> not routed.
        # 2026-10-27: auto/reasoning volatile (see "reasoning") -> after the steady routes.
        "translate":["gemini","omniroute:ddgw/gpt-5.4-mini","omniroute:cfp/zai-org/glm-5.2","nvidia-nim","omniroute:auto/reasoning"],
    }
    def _gateway(self,model,messages,max_tokens=1500,timeout=120):
        """OmniRoute local gateway (127.0.0.1:20128, Anthropic format); token from the vault, never printed."""
        try:
            import _secrets
            tok=_secrets.get("omniroute.access_token")
        except Exception:
            tok=None
        if not tok: return "__ERR__ omniroute no-token"
        body=json.dumps({"model":model,"max_tokens":max_tokens,"messages":messages}).encode("utf-8")
        req=urllib.request.Request("http://127.0.0.1:20128/v1/messages",data=body,method="POST",
            headers={"Content-Type":"application/json","anthropic-version":"2023-06-01","x-api-key":str(tok),"Authorization":"Bearer "+str(tok)})
        try:
            with urllib.request.urlopen(req,timeout=timeout) as r:
                d=json.loads(r.read().decode("utf-8","replace"))
        except Exception as e:
            return f"__ERR__ omniroute {type(e).__name__}"
        text="".join(b.get("text","") for b in d.get("content",[]) if isinstance(b,dict)).strip()
        return text or "__ERR__ omniroute empty"
    # 2026-10-16 (ai_trader F1S proposal): free-pool RPD was unmeasured, so a background bulk/extract job could
    # only learn a provider was spent by buying 429s. chat_for now meters every call into api_budget's ledger
    # (_logs/api-usage/<seat>.jsonl, provider level, no key values) and skips a provider the ledger says is
    # parked or out of observed rpd -- the job stops itself; `api_budget.py learn --write` turns 429s into ceilings.
    METER_KEY="pool"
    def _budget_ok(self,provider):
        """False only when the ledger says `provider` is parked (recent 429) or over its measured rpd/rpm.
        No ledger, no budget, or any error = usable (UNKNOWN never blocks)."""
        try:
            import api_budget
            return bool(api_budget.headroom(provider,self.METER_KEY)["usable"])
        except Exception:
            return True
    def _budget_note(self,provider,task,out,model=None):
        """Append one ledger row for a chat_for call; a 429/quota error records `ratelimited` (auto-park)."""
        try:
            import api_budget
            low=(out or "").lower()
            if not low.startswith("__err__"): outcome="ok"
            elif "429" in low or "quota" in low or "ratelimit" in low or "rate limit" in low: outcome="ratelimited"
            else: outcome="error"
            api_budget.record(provider,self.METER_KEY,capability=f"chat_for.{task}",outcome=outcome,model=model,
                              detail="" if outcome=="ok" else (out or "")[:120])
        except Exception:
            pass
    @staticmethod
    def _json_ok(text):
        """True when `text` is a JSON document (a ```json fence around it is tolerated). jsonmode callers only."""
        t=(text or "").strip()
        if t.startswith("```"):
            t=t.strip("`").strip()
            if t[:4].lower()=="json": t=t[4:].strip()
        try:
            json.loads(t); return True
        except Exception:
            pass
        # callers (f1s-harvest, news_tone_label) parse the outermost {...} / [...] out of a short preamble: same rule here
        for a,b in (("{","}"),("[","]")):
            i,j=t.find(a),t.rfind(b)
            if 0<=i<j:
                try:
                    json.loads(t[i:j+1]); return True
                except Exception:
                    pass
        return False
    def chat_for(self,task,messages,jsonmode=False,max_tokens=1500):
        """Task-routed free call: the measured best provider for `task` first, then the next, then the generic
        cloud-first chain. Unknown task = chat(). Never raises; '__ERR__ ...' only when everything failed.
        Every routed call is metered (see _budget_note); a parked / spent provider is skipped, not bought.
        jsonmode=True (2026-10-18, ai_trader): a route that answers in prose is a failure (`not-json`), metered as
        `error`, and the next route is tried -- the caller never has to parse to find out the pool fell over."""
        last="__ERR__ no-route"
        avail=set(self.available_providers())
        for route in self.TASK_ROUTES.get(task,[]):
            if route.startswith("omniroute:"):
                prov,model="omniroute",route.split(":",1)[1]
            elif route.startswith("nvidia:"):
                if "nvidia-nim" not in avail: continue
                if not self._budget_ok("nvidia-nim"):
                    last="__ERR__ nvidia-nim budget-parked"; continue
                model=route.split(":",1)[1]
                last=self.chat_model("nvidia-nim",model,messages,jsonmode=jsonmode,max_tokens=max_tokens)
                if jsonmode and not last.startswith("__ERR__") and not self._json_ok(last):
                    last=f"__ERR__ nvidia-nim not-json {model}: {last[:60]!r}"
                self._budget_note("nvidia-nim",task,last,model)
                if not last.startswith("__ERR__"):
                    return last
                continue
            elif route in avail:
                prov,model=route,None
            else:
                continue
            if not self._budget_ok(prov):
                last=f"__ERR__ {prov} budget-parked"
                continue
            if model:
                last=self._gateway(model,messages,max_tokens=max_tokens)
            else:
                last=self.chat_via(prov,messages,jsonmode=jsonmode,max_tokens=max_tokens)
            if jsonmode and not last.startswith("__ERR__") and not self._json_ok(last):
                last=f"__ERR__ {prov} not-json {(model or prov)}: {last[:60]!r}"
            self._budget_note(prov,task,last,model)
            if not last.startswith("__ERR__"):
                return last
        out=self.chat(messages,jsonmode=jsonmode,max_tokens=max_tokens)
        return out if not out.startswith("__ERR__") else last if task in self.TASK_ROUTES else out
    def fan_out(self,jobs,task=None,jsonmode=False,max_tokens=1500,workers=4):
        """operator 2026-10-27 「時間最貴…叫不同的免費模型去執行可以被免費模型執行的足夠簡單任務」: run independent
        jobs (each a messages list) at the same time, one free provider per job round-robin, so separate free quotas
        work in parallel. A job that fails, or answers prose under jsonmode, falls back to chat_for(task) / chat().
        Returns answers in job order; '__ERR__ ...' only for a job every route failed."""
        from concurrent.futures import ThreadPoolExecutor
        jobs=list(jobs)
        if not jobs: return []
        provs=[p for p in self.available_providers() if p!="ollama" and self.circuits.allowed(p) and self._budget_ok(p)]
        def one(item):
            i,msgs=item
            out=self.chat_via(provs[i%len(provs)],msgs,jsonmode=jsonmode,max_tokens=max_tokens) if provs else "__ERR__ no-provider"
            if out.startswith("__ERR__") or (jsonmode and not self._json_ok(out)):
                out=self.chat_for(task,msgs,jsonmode=jsonmode,max_tokens=max_tokens) if task else self.chat(msgs,jsonmode=jsonmode,max_tokens=max_tokens)
            return out
        with ThreadPoolExecutor(max_workers=max(1,min(workers,len(jobs)))) as ex:
            return list(ex.map(one,enumerate(jobs)))
    def chat_via(self,provider,messages,jsonmode=False,max_tokens=1500,timeout=None):
        """Call one provider with persistent failure isolation and attribution."""
        p=(provider or "").lower()
        if p!="ollama" and self._creds(p) is False:
            # 2026-10-27 audit: cerebras/cf_ai/hf/... had no status=ok key, yet every fallback chain called them and
            # recorded `provider-call-failed`, so the health file blamed the provider for an empty key pool.
            if hasattr(self.circuits,"note"):
                self.circuits.note(p,"no-credentials","no status=ok key in api-matrix (see key-health.py summary)")
            return f"__ERR__ {p} no-credentials"
        if not self.circuits.allowed(p):
            return f"__ERR__ {p} circuit-open"
        if p=="groq": raw=self._groq(messages,jsonmode,max_tokens)
        elif p=="cerebras": raw=self._oai(self.cerebras or [],"https://api.cerebras.ai/v1/chat/completions",messages,jsonmode,max_tokens,timeout or 90)
        elif p=="openrouter": raw=self._oai(self.openrouter or [],"https://openrouter.ai/api/v1/chat/completions",messages,jsonmode,max_tokens,timeout or 90)
        elif p=="cf_ai": raw=self._cf(messages,jsonmode,max_tokens,timeout or 90)
        elif p=="hf": raw=self._hf(messages,jsonmode,max_tokens)
        elif p=="gemini": raw=self._gemini(messages,jsonmode)
        elif p=="ollama":
            if not self._local_enabled(): return "__ERR__ ollama disabled (A770 endpoint or not cpu_only)"
            if not self._ollama_up(): return "__ERR__ ollama unreachable"
            if not self._local_grant(): return "__ERR__ ollama load-grant refused"
            raw=self._oai([(None,self.ollama_model)],self.ollama_url,messages,jsonmode,max_tokens,timeout or 240)
        elif p in self.XPROV:
            url,fam,keys=self.XPROV[p]
            raw=self._oai(keys or [],url,messages,jsonmode,max_tokens,timeout or 90)
        else: return f"__ERR__ unknown provider {provider}"
        failed=isinstance(raw,str) and raw.startswith("__ERR__")
        # keep the real (redacted) cause in the health file: "provider-call-failed" alone hid 402/403/410 causes
        self.circuits.record(p,not failed,("provider-call-failed: "+redact(raw[8:])[:130]) if failed else "ok")
        return raw
    def _creds(self,p):
        """True/False when the provider's key pool is known non-empty/empty; None for an unknown provider name."""
        g=lambda a: getattr(self,a,None)
        pools={"groq":g("groq"),"cerebras":g("cerebras"),"openrouter":g("openrouter"),"cf_ai":g("cf_ai"),
               "hf":g("hfkeys"),"gemini":g("gemkeys")}
        pools.update({k:v[2] for k,v in (g("XPROV") or {}).items()})
        if p not in pools or pools[p] is None: return None   # unknown name, or a partially built Pool (tests)
        return bool(pools[p])
    def _oai_stream(self,provkeys,url,messages,max_tokens,thinking=False,timeout=420,idle=120):
        """Streaming OpenAI-compatible call that keeps only the answer text. Reasoning models spend thousands of
        tokens thinking first: ai_ziyaoastro's 2026-10-24 evaluation got empty content from all four NVIDIA reasoning
        models through the non-streaming 4,096-token path, and answers once streamed with 12,000 tokens and thinking
        off (chat_template_kwargs). `timeout` caps the whole answer, `idle` each read."""
        last="none"
        for key,model in provkeys:
            d={"model":model,"messages":messages,"max_tokens":max_tokens,"temperature":0.2,"stream":True}
            if not thinking:
                d["chat_template_kwargs"]={"enable_thinking":False,"thinking":False}
            hdr={"Content-Type":"application/json","User-Agent":UA}
            if key: hdr["Authorization"]=f"Bearer {key}"
            parts=[]; finish=None; reasoning=0; t0=time.time()
            try:
                req=urllib.request.Request(url,data=json.dumps(d).encode(),method="POST",headers=hdr)
                with urllib.request.urlopen(req,timeout=idle) as r:
                    for raw in r:
                        line=raw.decode("utf-8","replace").strip()
                        if not line.startswith("data:") or line.endswith("[DONE]"):
                            continue
                        ch=(json.loads(line[5:]).get("choices") or [{}])[0]
                        dl=ch.get("delta") or {}
                        reasoning+=len(dl.get("reasoning_content") or dl.get("reasoning") or "")
                        parts.append(dl.get("content") or "")
                        finish=ch.get("finish_reason") or finish
                        if time.time()-t0>timeout:
                            finish="client-cap"; break
            except urllib.error.HTTPError as e:
                last=f"oai-stream-failed ({e.code})"; continue
            except Exception as e:  # noqa: BLE001 - a cut stream keeps what it already received
                if not "".join(parts).strip():
                    last=f"oai-stream-failed ({type(e).__name__})"; continue
                finish=f"cut:{type(e).__name__}"
            text="".join(parts).strip()
            if text:
                return text
            last=f"empty-content (finish={finish}, reasoning={reasoning})"
        return f"__ERR__ {last}"
    def chat_model(self,provider,model,messages,jsonmode=False,max_tokens=12000,timeout=None,thinking=False,stream=True):
        """One model of a multi-model OpenAI-compatible provider, e.g. NVIDIA's free catalog (operator 2026-10-24,
        reel De1UihACGPs). Its breaker key is `provider:model`: in the 2026-10-24 probe 4 of 8 catalog models answered
        404 for this account, and one bad model must not close the provider for the working ones. Streams with
        thinking off and a 12,000-token budget by default (see _oai_stream); jsonmode uses the plain call."""
        key=f"{(provider or '').lower()}:{model}"
        if not self.circuits.allowed(key):
            return f"__ERR__ {key} circuit-open"
        prov=self.XPROV.get((provider or "").lower())
        if not prov:
            return f"__ERR__ unknown provider {provider}"
        url,_fam,keys=prov
        pk=[(k,model) for k,_m in (keys or [])]
        if stream and not jsonmode:
            raw=self._oai_stream(pk,url,messages,max_tokens,thinking=thinking,timeout=timeout or 420)
        else:
            raw=self._oai(pk,url,messages,jsonmode,max_tokens,timeout or 120)
        failed=isinstance(raw,str) and raw.startswith("__ERR__")
        self.circuits.record(key,not failed,"provider-call-failed" if failed else "ok")
        return raw
    def ask_json(self,prompt,system=None):
        msgs=([{"role":"system","content":system}] if system else [])+[{"role":"user","content":prompt}]
        raw=self.chat(msgs,jsonmode=True)
        try: return json.loads(raw)
        except Exception: return {"__parse_error__":raw[:200]}
    def digest(self,text):
        return self.chat([{"role":"system","content":SYS_DIGEST},
                          {"role":"user","content":text[:24000]}])

# ---- input scanning -------------------------------------------------------
def pending_inputs(include_all=False):
    out=[]
    for dp,dn,fn in os.walk(I):
        if any(x in dp for x in("_digested","_archive","_ai_drafts","_staging")): continue
        for f in fn:
            if not f.endswith((".md",".txt")) or f.lower()=="readme.md": continue
            p=os.path.join(dp,f); rel=os.path.relpath(p,I); tk=os.path.getsize(p)//4
            # bare-link / pending-links records are never auto-digested (would hallucinate)
            if "pending-links" in f.lower(): continue
            trivial=("from_line" in rel) or ("ecosystem-auto" in f) or tk<120
            if trivial and not include_all: continue
            out.append((rel,p,tk))
    return sorted(out,key=lambda x:-x[2])

# ---- the gate (worthiness + adversarial source-faithfulness) --------------
GATE_SYS=("You are a STRICT adversarial reviewer for a technical knowledge base. "
"Assume the draft is flawed; hunt for problems. Be harsh. You enforce a rubric "
"(00-meta/CURATION-RUBRIC.md); OVER-WEIGHT reusability (D1) and concreteness (D3) "
"because lenient judges over-rate interesting-but-unactionable blurbs. Default to a "
"LOW score when uncertain on those two.")
def gate(pool,draft,source):
    p=("SOURCE (ground truth):\n"+(source or "(none)")+"\n\n---DRAFT---\n"+draft[:5000]+"\n\n"
    "Judge two things against the rubric.\n"
    "1) WORTH (1-5): is this a GENUINELY reusable cross-project technical technique? "
    "AUTO worth<=2 if ANY: a personal note/chat/status message; a single bare URL; a thin "
    "news/release blurb with NO transferable mechanism; an error stub or one-off log line; "
    "OR advice that is all abstract adjectives ('be careful','improve quality') with zero "
    "concrete command/path/flag/threshold (D3 fails). worth>=4 ONLY if it names a trap AND a "
    "fix with at least one concrete artifact a future session could act on.\n"
    "2) FABRICATED (bool): does the DRAFT state technical specifics (commands, file paths, version "
    "numbers, metrics, mechanisms) NOT present in the SOURCE? IGNORE template scaffolding entirely "
    "(front-matter last_updated/version, section headings, generic 'UNVERIFIED seed' boilerplate, "
    "generic sources line) — that is REQUIRED format, not fabrication.\n"
    'Return JSON {"worth":1-5,"fabricated":true_or_false,"why":"<=8 words"}.')
    j=pool.ask_json(p,system=GATE_SYS)
    j["promote"]=(isinstance(j.get("worth"),int) and j["worth"]>=4 and not j.get("fabricated",True))
    return j

TIEBREAK_SYS=("You are a second, INDEPENDENT senior reviewer for a high-quality reusable "
"technique knowledge base. Be conservative; default to NO when thin or uncertain.")
def second_opinion(pool,draft,source):
    """Perspective-diverse tie-breaker for borderline drafts. Default NO on uncertainty."""
    p=("SOURCE:\n"+(source or "(none)")+"\n\n---DRAFT---\n"+draft[:5000]+"\n\n"
    "Does this belong in the KB as a canonical, reusable cross-project technique, with NO "
    "fabricated specifics beyond the source? Default NO if thin, personal, or uncertain. "
    'Return JSON {"promote":true_or_false,"why":"<=8 words"}.')
    return bool(pool.ask_json(p,system=TIEBREAK_SYS).get("promote"))

def placement(pool,draft_head,existing):
    p=(f"Folders: {FOLDERS}\nExisting filenames: {sorted(existing)[:120]}\n\n---DRAFT HEAD---\n"
       +draft_head[:1500]+'\n\nPick the best target folder and a short kebab-case filename '
       '(no date, no .md). Return JSON {"folder":"50-techniques","slug":"my-technique"}.')
    j=pool.ask_json(p)
    fo=j.get("folder") if j.get("folder") in FOLDERS else "50-techniques"
    slug=re.sub(r'[^a-z0-9]+','-',(j.get("slug") or "").lower()).strip('-')[:50]
    if not slug or slug=="untitled":
        # model returned no usable slug (common with the weaker local-floor model):
        # derive a kebab slug from the draft's H1 title so a promotion never lands as
        # untitled.md. see 50-techniques/multi-provider-llm-fallback.md (KB 2026.06.06-1)
        h1=re.search(r'^#\s+(.+)$',draft_head,flags=re.M)
        slug=(re.sub(r'[^a-z0-9]+','-',h1.group(1).lower()).strip('-')[:50] if h1 else "")
    slug=slug or "untitled"
    return fo,slug

# ---- promotion / staging --------------------------------------------------
def existing_filenames():
    return [f for fo in FOLDERS for f in (os.listdir(os.path.join(O,fo)) if os.path.isdir(os.path.join(O,fo)) else [])]

def promote(draft_text,folder,slug):
    body=re.sub(r'\n*<!-- AI-DRAFT.*?-->\n*','\n',draft_text,flags=re.S).rstrip()+"\n"
    tgt=os.path.join(O,folder,slug+".md"); c=2
    while os.path.exists(tgt): tgt=os.path.join(O,folder,f"{slug}-{c}.md"); c+=1
    open(tgt,"w",encoding="utf-8").write(body)
    return os.path.relpath(tgt,HUB)

def archive_source(srcrel,tag="auto"):
    if not srcrel: return
    sp=os.path.join(I,srcrel.replace("/","\\"))
    if not os.path.exists(sp): return
    import shutil
    arch=os.path.join(I,"_digested","2026-06-04-"+tag); os.makedirs(arch,exist_ok=True)
    shutil.move(sp,os.path.join(arch,os.path.basename(sp)))

def stage_draft(name,text,srcrel,source_text=None):
    os.makedirs(DRAFTS,exist_ok=True)
    base=re.sub(r'[^a-z0-9]+','-',os.path.splitext(os.path.basename(name))[0].lower())
    text=text.rstrip()+f"\n\n<!-- AI-DRAFT from technique_input/{srcrel} — review before promoting -->\n"
    p=os.path.join(DRAFTS,base+".md"); open(p,"w",encoding="utf-8").write(text)
    if source_text:  # sidecar so the gate can ground drafts whose source is not a file
        open(os.path.join(DRAFTS,base+".src.txt"),"w",encoding="utf-8").write(source_text[:12000])
    return p

def draft_source(draft_path,draft_text):
    """Resolve a draft's ground-truth source: input file, else sidecar, else ''."""
    m=re.search(r'from technique_input/(.+?) —',draft_text)
    if m:
        sp=os.path.join(I,m.group(1).split(" (")[0].replace("/","\\"))
        if os.path.exists(sp): return open(sp,encoding="utf-8-sig",errors="replace").read(), m.group(1)
    side=os.path.splitext(draft_path)[0]+".src.txt"
    if os.path.exists(side): return open(side,encoding="utf-8-sig",errors="replace").read(), (m.group(1) if m else "")
    return "", (m.group(1) if m else "")

if __name__=="__main__":
    import sys
    a=sys.argv[1:]
    pool=Pool()
    if a and a[0]=="panel":
        n=int(a[1]) if len(a)>1 and a[1].isdigit() else 4
        pl=pool.panel(n)
        print("decorrelated adversarial panel (%d voters, distinct families):"%len(pl))
        for prov,fam in pl: print("  %-12s family=%s"%(prov,fam))
        fams=[f for _,f in pl]
        print("families:",fams,"| unique:",len(set(fams))==len(fams))
    elif a and a[0]=="providers":
        print("credentialed providers:",pool.available_providers())
        print("extra providers WITH keys:",[p for p,(u,f,k) in pool.XPROV.items() if k])
        print("extra providers PENDING (no key yet):",[p for p,(u,f,k) in pool.XPROV.items() if not k])
        # cf_ai is env-aware (needs key AND account_id); report it separately
        print("cf_ai:", "ACTIVE (%d url/key entries)"%len(pool.cf_ai) if pool.cf_ai
              else "PENDING (no key+account_id yet)")
    else:
        print("usage: _llm.py [panel [n] | providers]")
