/**
 * THE BACKSTORY CHRONICLE — FRONTEND ENGINE
 * Handles ingestion, YouTube extraction, API calls, broadsheet rendering, 
 * followed sources management, schedule/refresh triggers, and newsletter generation.
 */

// State
const state = {
    currentTheme: 'theme-newsprint',
    currentView: 'newspaper', // 'newspaper' | 'newsletter' | 'raw'
    activeInputMode: 'urls',   // 'urls' | 'youtube' | 'raw' | 'site'
    articles: [],
    sources: [],
    fontSizeLevel: 0,
    isSpeaking: false,
    synthUtterance: null,
};

// Preset Demo Articles & Sources
const PRESETS = {
    multisource: [
        {
            url: "https://www.youtube.com/watch?v=kCc8FmEb1nY",
            title: "Next-Gen AI Hardware & Quantum Optical Interconnects",
            deck: "MKBHD & AnandTech deep-dive into how optical interconnects and dedicated inference silicon are revolutionizing real-time computing.",
            author: "Marques Brownlee (MKBHD)",
            published_date: "2026-09-19",
            category: "Technology & AI",
            extraction_method: "youtube_transcript",
            fetch_strategy: "direct",
            is_video: true,
            video_id: "kCc8FmEb1nY",
            image_url: "https://images.unsplash.com/photo-1518770660439-4636190af475?w=800&auto=format&fit=crop&q=80",
            image_caption: "Silicon photonics and multi-die packaging tested under high-load synthetic inference benchmarks.",
            callout_title: "Key Video Takeaway:",
            callout_text: "Memory bandwidth and interconnect latency have overtaken raw FLOPs as the crucial metric in scaling local neural agents.",
            cross_source_count: 3,
            related_sources: [
                { title: "MKBHD Studio Review", url: "https://www.youtube.com/watch?v=kCc8FmEb1nY", source_type: "youtube_video" },
                { title: "The Verge Hardware Breakdown", url: "https://www.theverge.com/tech", source_type: "website" },
                { title: "Stratechery Silicon Analysis", url: "https://stratechery.com", source_type: "rss" }
            ],
            summary: "A comprehensive investigation into the transition from copper traces to co-packaged optical transceivers. Test-time compute scaling is creating unprecedented demand for low-latency memory clustering.",
            takeaways: [
                "Optical interconnects reduce thermal throttling across dense rack architectures",
                "Co-packaged optics enable clusters of thousands of chips to operate as unified shared memory",
                "Video teardown reveals custom liquid cooling loops engineered for 2kW accelerators"
            ],
            text: `Modern generative intelligence architectures have pushed traditional copper interconnects beyond their physical boundaries. In this deep dive, we examine the mechanical and thermal innovations required to deploy co-packaged optics directly onto accelerator substrates.\n\nBy converting electrical signals to laser light at the chip edge, data transfer latency drops by an order of magnitude while saving up to 40% in interconnect power dissipation.\n\nAs models scale their test-time compute through reasoning loops, memory coherence across distributed clusters becomes the decisive bottleneck in real-time response generation.`
        },
        {
            url: "https://stratechery.com/2026/neural-interfaces",
            title: "The Architecture of Frontier Intelligence: Models, Silicon, and Power",
            deck: "Why high-bandwidth memory and dedicated nuclear energy sourcing define the next epoch of computing infrastructure.",
            author: "Ben Thompson / Stratechery",
            published_date: "2026-09-18",
            category: "Technology & AI",
            extraction_method: "trafilatura",
            fetch_strategy: "direct",
            image_url: "https://images.unsplash.com/photo-1526374965328-7f61d4dc18c5?w=400&auto=format&fit=crop&q=80",
            highlight_tag: "Analysis",
            summary: "Datacenter scaling requires multi-gigawatt power contracts and proprietary optical fabrics to prevent distributed cluster bottlenecks.",
            takeaways: [
                "Test-time compute and reasoning models are reorganizing AI deployment economics",
                "High-bandwidth optical interconnects form a steep competitive moat for frontier labs"
            ],
            text: `Large-scale neural network development has shifted from pure parameter count scaling to a complex optimization spanning memory hierarchy, inference latency, and power availability.\n\nInference clusters capable of speculative decoding are driving new hardware paradigms across the industry.`
        },
        {
            url: "https://overreacted.io/a-complete-guide",
            title: "Zero-Cost Concurrency in Next-Generation Runtimes",
            deck: "How modern asynchronous engines eliminate thread overhead and memory leaks.",
            author: "Dan Abramov",
            published_date: "2026-09-17",
            category: "Software Engineering",
            extraction_method: "trafilatura",
            fetch_strategy: "direct",
            image_url: "https://images.unsplash.com/photo-1555066931-4365d14bab8c?w=400&auto=format&fit=crop&q=80",
            pull_quote: "“Structured concurrency ensures that child coroutines cannot outlive their calling parent scope.”",
            summary: "Structured concurrency brings deterministic lifecycles to asynchronous codebases, drastically reducing memory leaks.",
            takeaways: [
                "Tasks are bound directly to lexical blocks for deterministic cleanup",
                "Eliminates memory leaks historically common in complex async codebases"
            ],
            text: `Structured concurrency ensures that child coroutines cannot outlive their calling parent scope. By binding task lifecycles directly to lexical blocks, complex asynchronous architectures become dramatically simpler to reason about, test, and debug.`
        }
    ],
    yt_tech: [
        {
            url: "https://www.youtube.com/watch?v=kCc8FmEb1nY",
            title: "MKBHD Teardown: Why Every Tech Giant is Building Custom Silicon",
            deck: "From Apple Silicon to Google TPUs and Tesla Dojo — how custom processors outrun commodity GPUs.",
            author: "Marques Brownlee (MKBHD)",
            published_date: "2026-09-19",
            category: "Hardware & Tech",
            extraction_method: "youtube_transcript",
            fetch_strategy: "direct",
            is_video: true,
            video_id: "kCc8FmEb1nY",
            image_url: "https://images.unsplash.com/photo-1518770660439-4636190af475?w=800&auto=format&fit=crop&q=80",
            image_caption: "Silicon wafer packaging inspection in MKBHD Studio lab.",
            callout_title: "Studio Verdict:",
            callout_text: "Custom ASICs provide a 5x efficiency advantage for specialized model architectures, prompting a massive industry shift away from off-the-shelf accelerators.",
            summary: "Marques explores why every major technology company has vertically integrated silicon engineering teams, designing custom matrix multiplication engines specifically tailored to their proprietary software architectures.",
            takeaways: [
                "Domain-specific accelerators reduce inference power draw by over 60%",
                "Vertical software-hardware integration minimizes kernel launching overhead",
                "Supply chain resilience remains the top driver for custom ASIC investments"
            ],
            text: `In this episode, we break down why off-the-shelf GPUs are no longer enough for hyperscale tech companies. By co-designing microcode, cache hierarchy, and matrix processing units directly for proprietary model topologies, companies gain enormous cost and speed advantages.\n\nWe examine chip die shots, interconnect bus bandwidths, and thermal efficiency benchmarks under sustained multi-token generation workloads.`
        }
    ],
    yt_ai: [
        {
            url: "https://www.youtube.com/watch?v=aircAruvnKk",
            title: "3Blue1Brown: Visualizing Attention & Transformers in Geometric Space",
            deck: "A visual exploration of high-dimensional attention weights and semantic vector projections.",
            author: "Grant Sanderson (3Blue1Brown)",
            published_date: "2026-09-19",
            category: "AI & Mathematics",
            extraction_method: "youtube_transcript",
            fetch_strategy: "direct",
            is_video: true,
            video_id: "aircAruvnKk",
            image_url: "https://images.unsplash.com/photo-1509228468518-180dd4864904?w=800&auto=format&fit=crop&q=80",
            image_caption: "Multi-head attention projections mapped onto a 3D manifold visualizer.",
            callout_title: "Mathematical Insight:",
            callout_text: "Attention matrices act as dynamic routing filters, continuously re-weighting contextual embeddings across token sequences.",
            summary: "Grant Sanderson provides an intuitive visual foundation for understanding how self-attention matrices project token tokens through query, key, and value manifolds to capture nuance and long-range dependencies.",
            takeaways: [
                "Self-attention dynamically projects vectors into high-dimensional latent space",
                "Softmax normalization ensures gradient stability during backpropagation",
                "Multi-head attention allows simultaneous capture of syntactic and semantic patterns"
            ],
            text: `How do transformers actually understand grammar, nuance, and code? Rather than treating neural networks as black boxes, Grant Sanderson visualizes the geometric transformations applied at each layer.\n\nBy following word vectors through attention heads, we see how words shift their semantic coordinates depending on the surrounding context.`
        }
    ],
    yt_fireship: [
        {
            url: "https://www.youtube.com/watch?v=sB1e6n953x8",
            title: "Fireship: 10 New Tech Stacks You Need to Know (In 100 Seconds)",
            deck: "From Bun 2.0 to local neural runtimes and WebAssembly component models.",
            author: "Jeff Delaney (Fireship)",
            published_date: "2026-09-19",
            category: "Developer Tools",
            extraction_method: "youtube_transcript",
            fetch_strategy: "direct",
            is_video: true,
            video_id: "sB1e6n953x8",
            image_url: "https://images.unsplash.com/photo-1555066931-4365d14bab8c?w=800&auto=format&fit=crop&q=80",
            image_caption: "High-speed overview of cutting-edge web and runtime toolchains.",
            callout_title: "Speed Briefing:",
            callout_text: "High-performance native runtimes (Zig, Rust, Mojo) are rapidly displacing legacy scripting layers in modern backend infrastructure.",
            summary: "A rapid-fire dispatch covering the most disruptive software frameworks, highlighting native binary compilation, zero-overhead runtimes, and local AI toolchains.",
            takeaways: [
                "WebAssembly component models bring true language interoperability",
                "Edge compute runtimes start in under 5ms using lightweight V8 isolates"
            ],
            text: `Welcome back to Fireship. Today we are breaking down 10 brand-new tools reshaping modern software engineering.\n\nFrom memory-safe low-level languages to distributed state engines, here is everything developers need to keep pace with an accelerating ecosystem.`
        }
    ],
    church: [
        {
            url: "https://example.org/parish/experience-gods-love",
            title: "Experience God's Love in Our Church: A Sacred Sanctuary",
            deck: "Sequased et har lam, in-nistiusae im vento — finding peace and communion in an ever-shifting modern age.",
            author: "The Editorial Board / Father Thomas",
            published_date: "2026-09-19",
            category: "Faith & Community",
            extraction_method: "editorial_press",
            fetch_strategy: "direct",
            image_url: "https://images.unsplash.com/photo-1548625361-195fe612b7f3?w=800&auto=format&fit=crop&q=80",
            image_caption: "Excepelessi minctemo turem, que voluptatis num volup, Sam te sero sent eros.",
            callout_title: "Our Church's Mission:",
            callout_text: "Tempeleste — Nequi oust quiet in velleut diero laguate corus eos am qui sent ducil. Come join us every Sunday at morning worship and fellowship.",
            summary: "Under the soaring stone arches and radiant stained glass of our sanctuary, generations of seekers have found solace, purpose, and enduring fellowship. Divine love is expressed through communal grace, charity, and open-hearted fellowship.",
            takeaways: [
                "Weekly ministries encompass community food distribution and youth education",
                "Sunday services feature contemplative choir music and open community fellowship",
                "Dedicated pastoral care offering solace in an accelerating technological age"
            ],
            text: `Under the soaring stone arches and radiant stained glass of our sanctuary, generations of seekers have found solace, purpose, and enduring fellowship. As our world accelerates with relentless technological change, the timeless sanctuary of contemplative faith provides an anchor for the soul.\n\nIn our congregation, we believe that divine love is not an abstract concept confined to ancient scriptures, but a living, breathing reality expressed through communal grace, charity, and open-hearted fellowship. Every person walking through our doors is welcomed without pretense or judgment.\n\nOur weekly ministries encompass community food distribution, interfaith dialogues, youth education, and contemplative choir music. We invite you to join us for our Sunday morning services and experience the profound stillness and warmth of a community united in purpose and kindness.`
        },
        {
            url: "https://example.org/parish/come-as-you-are",
            title: "Come As You Are: Our Sanctuary Welcomes Everyone",
            deck: "An open invitation to neighborhood families and seekers across all backgrounds.",
            author: "Sister Margaret",
            published_date: "2026-09-18",
            category: "Faith & Community",
            extraction_method: "trafilatura",
            fetch_strategy: "direct",
            image_url: "https://images.unsplash.com/photo-1519817650390-64a93db51149?w=400&auto=format&fit=crop&q=80",
            highlight_tag: "Highlight",
            summary: "Faith thrives when barriers fall away. Our community doors are wide open to individuals and families from every background.",
            takeaways: [
                "Open communion and fellowship every weekend",
                "Accessible support programs for neighborhood families"
            ],
            text: `Faith thrives when barriers fall away. Our community doors are wide open to individuals and families from every background, offering warm hospitality, community support, and uplifting musical services every weekend.`
        },
        {
            url: "https://example.org/parish/about-us",
            title: "About Our Fellowship & Outreach Programs",
            deck: "Serving local communities with compassionate care and weekly outreach.",
            author: "Deacon Michael",
            published_date: "2026-09-17",
            category: "Outreach",
            extraction_method: "trafilatura",
            fetch_strategy: "direct",
            image_url: "https://images.unsplash.com/photo-1438232992991-995b7058bbb3?w=400&auto=format&fit=crop&q=80",
            pull_quote: "“In quietness and confidence shall be your strength.” — Isaiah 30:15",
            summary: "Founded with a vision of radical compassion, our parish outreach programs provide meals, tutoring, and family support.",
            takeaways: [
                "Over 500 local residents served weekly through outreach",
                "Volunteer-driven interfaith programs across the region"
            ],
            text: `Founded with a vision of radical compassion, our parish outreach programs provide meals, educational tutoring, and family counseling services to over five hundred local residents each week.\n\nThrough volunteer engagement and generous neighborhood contributions, our mission continues to expand across the metropolitan region.`
        }
    ],
    tech: [
        {
            url: "https://stratechery.com/2026/neural-interfaces",
            title: "The Architecture of Frontier Intelligence: Models, Silicon, and Power",
            deck: "Why the intersection of high-bandwidth memory, optical interconnects, and nuclear energy defines the next epoch of computing.",
            author: "Ben Thompson / Stratechery",
            published_date: "2026-09-19",
            category: "Technology & AI",
            extraction_method: "trafilatura",
            fetch_strategy: "direct",
            image_url: "https://images.unsplash.com/photo-1518770660439-4636190af475?w=800&auto=format&fit=crop&q=80",
            image_caption: "Next-generation datacenter clusters scaling beyond physical reticle constraints with custom optical fabrics.",
            callout_title: "Key Infrastructure Shift:",
            callout_text: "Memory bandwidth per FLOP has replaced raw compute as the primary bottleneck in continuous generative inference pipelines.",
            summary: "Large-scale neural network development has shifted from pure parameter count scaling to a complex optimization spanning memory hierarchy, inference latency, and power availability. Inference clusters capable of speculative decoding are driving new hardware paradigms.",
            takeaways: [
                "Test-time compute and reasoning models are reorganizing AI deployment economics",
                "High-bandwidth optical interconnects form a steep competitive moat for frontier labs",
                "Datacenter power scaling requires gigawatt-level dedicated energy sourcing"
            ],
            text: `The trajectory of large-scale neural network development has shifted from pure parameter count scaling to a multifaceted optimization problem spanning memory hierarchy, inference latency, and gigawatt-scale power availability.\n\nAs reasoning models demonstrate test-time compute gains, the economics of AI deployment are reorganizing around dedicated inference clusters capable of high-throughput speculative decoding.\n\nMoreover, the vertical integration of custom silicon with bespoke high-bandwidth optical interconnects represents the steepest competitive moat for frontier AI labs in this decade.`
        }
    ]
};

// Default fallback images pool for scraped articles
const DEFAULT_IMAGES = [
    "https://images.unsplash.com/photo-1548625361-195fe612b7f3?w=800&auto=format&fit=crop&q=80",
    "https://images.unsplash.com/photo-1518770660439-4636190af475?w=800&auto=format&fit=crop&q=80",
    "https://images.unsplash.com/photo-1497435334941-8c899ee9e8e9?w=800&auto=format&fit=crop&q=80",
    "https://images.unsplash.com/photo-1507842229451-9f75069732f1?w=800&auto=format&fit=crop&q=80",
    "https://images.unsplash.com/photo-1585829365295-ab7cd400c167?w=800&auto=format&fit=crop&q=80",
    "https://images.unsplash.com/photo-1451187580459-43490279c0fa?w=800&auto=format&fit=crop&q=80"
];

// Initialize on DOM load
document.addEventListener('DOMContentLoaded', () => {
    initThemePicker();
    initViewSwitcher();
    initInputTabs();
    initPresetButtons();
    initProcessHandler();
    initReaderModal();
    initPrintAndCopy();
    initFollowedSources();
    initManualRefresh();
    updateDateDisplay();

    // Load initial sources & default broadsheet (Multi-source preset showcasing YouTube + Articles)
    loadArticles(PRESETS.multisource);
    loadFollowedSources();
});

// ==========================================================================
// THEME & VIEW MANAGEMENT
// ==========================================================================

function initThemePicker() {
    const themeButtons = document.querySelectorAll('.theme-btn');
    themeButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            themeButtons.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            const theme = btn.dataset.theme;
            document.body.className = theme;
            state.currentTheme = theme;
        });
    });
}

function initViewSwitcher() {
    const viewButtons = document.querySelectorAll('.view-tab-btn');
    const views = {
        newspaper: document.getElementById('newspaperView'),
        newsletter: document.getElementById('newsletterView'),
        raw: document.getElementById('rawDataView'),
    };

    viewButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            viewButtons.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            const targetView = btn.dataset.view;
            state.currentView = targetView;

            Object.entries(views).forEach(([name, el]) => {
                if (name === targetView) {
                    el.style.display = 'block';
                } else {
                    el.style.display = 'none';
                }
            });

            if (targetView === 'newsletter') {
                renderNewsletterView(state.articles);
            } else if (targetView === 'raw') {
                renderRawJsonView(state.articles);
            }
        });
    });
}

function initInputTabs() {
    const inputTabs = document.querySelectorAll('.input-tab');
    const tabContents = {
        urls: document.getElementById('inputTab-urls'),
        youtube: document.getElementById('inputTab-youtube'),
        raw: document.getElementById('inputTab-raw'),
        site: document.getElementById('inputTab-site'),
    };

    inputTabs.forEach(tab => {
        tab.addEventListener('click', () => {
            inputTabs.forEach(t => t.classList.remove('active'));
            tab.classList.add('active');
            const mode = tab.dataset.inputMode;
            state.activeInputMode = mode;

            Object.entries(tabContents).forEach(([m, el]) => {
                if (el) {
                    if (m === mode) {
                        el.classList.add('active');
                    } else {
                        el.classList.remove('active');
                    }
                }
            });
        });
    });
}

function initPresetButtons() {
    const presetButtons = document.querySelectorAll('.preset-chip');
    presetButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            const presetKey = btn.dataset.preset;
            if (PRESETS[presetKey]) {
                loadArticles(PRESETS[presetKey]);
                showToast(`Loaded ${btn.textContent.trim()}`);
                
                const urls = PRESETS[presetKey].map(a => a.url).join('\n');
                const urlInput = document.getElementById('urlInput');
                const ytInput = document.getElementById('ytInput');
                if (urlInput) urlInput.value = urls;
                if (ytInput && presetKey.startsWith('yt_')) ytInput.value = urls;
            }
        });
    });
}

function updateDateDisplay() {
    const today = new Date();
    const options = { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' };
    const dateStr = today.toLocaleDateString('en-US', options).toUpperCase();
    
    const curDate = document.getElementById('currentDateDisplay');
    if (curDate) curDate.textContent = dateStr;

    const nlDate = document.getElementById('newsletterDateDisplay');
    if (nlDate) nlDate.textContent = `${today.toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric' })} • Curated Executive Edition`;
}

// ==========================================================================
// INGESTION & BACKEND PROCESSING
// ==========================================================================

function initProcessHandler() {
    const processBtn = document.getElementById('processBtn');
    processBtn.addEventListener('click', handleProcess);
}

async function handleProcess() {
    const mode = state.activeInputMode;
    const progressContainer = document.getElementById('progressContainer');
    const progressBarFill = document.getElementById('progressBarFill');
    const progressStatusText = document.getElementById('progressStatusText');
    const progressPercentText = document.getElementById('progressPercentText');

    progressContainer.style.display = 'block';
    progressBarFill.style.width = '15%';
    progressPercentText.textContent = '15%';
    progressStatusText.innerHTML = '<i data-lucide="loader-2" class="spin"></i> Contacting extraction &amp; summarization engine...';
    lucide.createIcons();

    try {
        let extractedArticles = [];

        if (mode === 'urls' || mode === 'youtube') {
            const inputEl = mode === 'youtube' ? document.getElementById('ytInput') : document.getElementById('urlInput');
            const urlText = inputEl ? inputEl.value.trim() : "";
            if (!urlText) {
                showToast('Please enter at least one URL or select a preset.', 'error');
                progressContainer.style.display = 'none';
                return;
            }
            const urls = urlText.split('\n').map(u => u.trim()).filter(u => u.startsWith('http'));
            if (urls.length === 0) {
                showToast('No valid URLs found. Make sure URLs start with http:// or https://', 'error');
                progressContainer.style.display = 'none';
                return;
            }

            progressBarFill.style.width = '40%';
            progressPercentText.textContent = '40%';
            progressStatusText.innerHTML = `<i data-lucide="loader-2" class="spin"></i> Extracting, transcribing &amp; summarizing ${urls.length} item(s)...`;
            lucide.createIcons();

            if (urls.length === 1) {
                const resp = await fetch('/extract', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ url: urls[0] })
                });
                const data = await resp.json();
                if (!resp.ok) {
                    throw new Error(data.detail || `Extraction failed with status ${resp.status}`);
                }
                if (data.is_listing && data.articles && data.articles.length > 0) {
                    extractedArticles = data.articles;
                } else {
                    extractedArticles = [data];
                }
            } else {
                const concurrency = parseInt(document.getElementById('concurrencySelect').value) || 5;
                const resp = await fetch('/extract/batch', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ urls: urls, max_concurrency: concurrency })
                });
                const data = await resp.json();
                if (!resp.ok) {
                    throw new Error(data.detail || `Batch extraction failed with status ${resp.status}`);
                }
                extractedArticles = [];
                for (const r of (data.results || [])) {
                    if (r.is_listing && r.articles && r.articles.length > 0) {
                        extractedArticles.push(...r.articles.filter(a => a.text && a.text.length > 50));
                    } else if (r.text && r.text.length > 50) {
                        extractedArticles.push(r);
                    }
                }
            }

        } else if (mode === 'raw') {
            const title = document.getElementById('rawTitle').value.trim() || "Collected Dispatch";
            const author = document.getElementById('rawAuthor').value.trim() || "Staff Writer";
            const body = document.getElementById('rawBody').value.trim();

            if (!body) {
                showToast('Please paste some text into the article body.', 'error');
                progressContainer.style.display = 'none';
                return;
            }

            const firstPeriod = body.indexOf('.');
            const deck = firstPeriod > 20 && firstPeriod < 180 ? body.slice(0, firstPeriod + 1) : body.slice(0, 140) + '...';

            extractedArticles = [{
                url: "pasted://direct-input",
                title: title,
                author: author,
                published_date: new Date().toISOString().slice(0, 10),
                text: body,
                char_count: body.length,
                extraction_method: "raw_text_ingestion",
                fetch_strategy: "direct",
                summary: body.slice(0, 350) + "...",
                deck: deck,
                takeaways: [
                    "Direct text dispatch processed into broadsheet and newsletter format",
                    "Ready for executive review, audio read-aloud, and PDF export"
                ],
                category: "Special Dispatch"
            }];

        } else if (mode === 'site') {
            const siteUrl = document.getElementById('siteUrlInput').value.trim();
            const siteType = document.getElementById('siteTypeSelect').value;

            if (!siteUrl) {
                showToast('Please enter a website or feed URL.', 'error');
                progressContainer.style.display = 'none';
                return;
            }

            progressBarFill.style.width = '35%';
            progressPercentText.textContent = '35%';
            progressStatusText.innerHTML = `<i data-lucide="loader-2" class="spin"></i> Discovering articles from ${siteUrl}...`;
            lucide.createIcons();

            const pollResp = await fetch('/extract/source-check', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ source_url: siteUrl, source_type: siteType })
            });
            const pollData = await pollResp.json();
            const newUrls = (pollData.new_item_urls || []).slice(0, 6);

            if (newUrls.length === 0) {
                const scrapeResp = await fetch('/scrape', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ url: siteUrl })
                });
                const scrapeData = await scrapeResp.json();
                extractedArticles = scrapeData.articles || [];
            } else {
                progressBarFill.style.width = '65%';
                progressPercentText.textContent = '65%';
                progressStatusText.innerHTML = `<i data-lucide="loader-2" class="spin"></i> Scraping, transcribing and summarizing ${newUrls.length} items...`;
                lucide.createIcons();

                const batchResp = await fetch('/extract/batch', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ urls: newUrls, max_concurrency: 4 })
                });
                const batchData = await batchResp.json();
                extractedArticles = (batchData.results || []).filter(r => r.text && r.text.length > 50);
            }
        }

        if (extractedArticles.length === 0) {
            throw new Error('No article or video text could be extracted. Check the URL or connection.');
        }

        progressBarFill.style.width = '100%';
        progressPercentText.textContent = '100%';
        progressStatusText.innerHTML = '<i data-lucide="check" style="color: #10b981;"></i> Processed and summarized successfully!';
        lucide.createIcons();

        loadArticles(extractedArticles);
        showToast(`Extracted & summarized ${extractedArticles.length} dispatches!`);

        setTimeout(() => {
            progressContainer.style.display = 'none';
        }, 1500);

    } catch (err) {
        console.error('Extraction error:', err);
        showToast(err.message || 'Extraction failed', 'error');
        progressBarFill.style.width = '0%';
        progressContainer.style.display = 'none';
    }
}

// ==========================================================================
// FOLLOWED SOURCES & SCHEDULE REFRESH MANAGEMENT
// ==========================================================================

function initFollowedSources() {
    const sourcesBtn = document.getElementById('followedSourcesBtn');
    const sourcesModal = document.getElementById('sourcesModal');
    const closeBtn = document.getElementById('closeSourcesBtn');
    const closeFooterBtn = document.getElementById('closeSourcesFooterBtn');
    const addBtn = document.getElementById('addSourceSubmitBtn');
    const seedBtn = document.getElementById('seedPresetSourcesBtn');
    const refreshFromModalBtn = document.getElementById('triggerRefreshFromModalBtn');

    if (sourcesBtn && sourcesModal) {
        sourcesBtn.addEventListener('click', () => {
            sourcesModal.style.display = 'flex';
            document.body.style.overflow = 'hidden';
            loadFollowedSources();
        });
    }

    const closeHandler = () => {
        if (sourcesModal) {
            sourcesModal.style.display = 'none';
            document.body.style.overflow = 'auto';
        }
    };

    if (closeBtn) closeBtn.addEventListener('click', closeHandler);
    if (closeFooterBtn) closeFooterBtn.addEventListener('click', closeHandler);
    if (sourcesModal) {
        sourcesModal.addEventListener('click', (e) => {
            if (e.target === sourcesModal) closeHandler();
        });
    }

    if (addBtn) {
        addBtn.addEventListener('click', handleAddSource);
    }

    if (seedBtn) {
        seedBtn.addEventListener('click', seedPresetSources);
    }

    if (refreshFromModalBtn) {
        refreshFromModalBtn.addEventListener('click', () => {
            closeHandler();
            triggerManualRefresh();
        });
    }
}

async function loadFollowedSources() {
    try {
        const resp = await fetch('/sources');
        if (!resp.ok) return;
        const data = await resp.json();
        state.sources = Array.isArray(data) ? data : (data.sources || []);
        
        const countBadge = document.getElementById('followedSourcesCountBadge');
        if (countBadge) countBadge.textContent = state.sources.length;

        renderFollowedSourcesList();
    } catch (err) {
        console.warn('Failed to load followed sources:', err);
    }
}

function renderFollowedSourcesList() {
    const listEl = document.getElementById('followedSourcesList');
    if (!listEl) return;

    if (state.sources.length === 0) {
        listEl.innerHTML = `
            <div style="text-align: center; color: var(--ink-muted); padding: 1.5rem; font-style: italic;">
                No followed sources added yet. Click <strong>"Load Recommended Sources"</strong> or add your favorite YouTube channels and RSS feeds above.
            </div>
        `;
        return;
    }

    listEl.innerHTML = state.sources.map(src => {
        let typeIcon = 'globe';
        let typeBadge = 'Website';
        if (src.type === 'youtube_channel' || src.type === 'youtube_video') {
            typeIcon = 'video';
            typeBadge = 'YouTube';
        } else if (src.type === 'rss') {
            typeIcon = 'rss';
            typeBadge = 'RSS Feed';
        }

        return `
            <div class="source-item" id="src-row-${src.id}">
                <div class="source-item-info">
                    <div style="display: flex; align-items: center; gap: 6px;">
                        <i data-lucide="${typeIcon}" style="width: 14px; height: 14px; color: var(--ink-accent);"></i>
                        <span class="source-item-name">${escapeHtml(src.name)}</span>
                        <span class="source-item-badge">${typeBadge}</span>
                    </div>
                    <span class="source-item-url">${escapeHtml(src.url)}</span>
                </div>
                <button type="button" class="source-item-del" onclick="deleteFollowedSource(${src.id})" title="Delete source">
                    <i data-lucide="trash-2" style="width: 15px; height: 15px;"></i>
                </button>
            </div>
        `;
    }).join('');

    lucide.createIcons();
}

async function handleAddSource() {
    const nameInput = document.getElementById('newSourceName');
    const typeSelect = document.getElementById('newSourceType');
    const urlInput = document.getElementById('newSourceUrl');

    const name = nameInput.value.trim();
    const type = typeSelect.value;
    const url = urlInput.value.trim();

    if (!name || !url) {
        showToast('Please enter both a source name and URL.', 'error');
        return;
    }

    try {
        const resp = await fetch('/sources', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, url, source_type: type })
        });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.detail || 'Failed to add source');

        showToast(`Added source: ${name}`);
        nameInput.value = '';
        urlInput.value = '';
        await loadFollowedSources();
    } catch (err) {
        showToast(err.message, 'error');
    }
}

async function deleteFollowedSource(id) {
    try {
        const resp = await fetch(`/sources/${id}`, { method: 'DELETE' });
        if (!resp.ok) throw new Error('Failed to delete source');
        showToast('Source removed.');
        await loadFollowedSources();
    } catch (err) {
        showToast(err.message, 'error');
    }
}

async function seedPresetSources() {
    const recommended = [
        { name: "MKBHD (YouTube)", url: "https://www.youtube.com/@mkbhd", source_type: "youtube_channel" },
        { name: "Fireship (YouTube)", url: "https://www.youtube.com/@Fireship", source_type: "youtube_channel" },
        { name: "The Verge", url: "https://www.theverge.com/rss/index.xml", source_type: "rss" },
        { name: "TechCrunch", url: "https://techcrunch.com/feed/", source_type: "rss" },
        { name: "Stratechery", url: "https://stratechery.com/feed/", source_type: "rss" }
    ];

    showToast('Adding recommended sources...');
    for (const rec of recommended) {
        await fetch('/sources', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(rec)
        });
    }
    await loadFollowedSources();
    showToast('Loaded recommended sources!');
}

function initManualRefresh() {
    const refreshBtn = document.getElementById('manualRefreshBtn');
    if (refreshBtn) {
        refreshBtn.addEventListener('click', triggerManualRefresh);
    }
}

async function triggerManualRefresh() {
    const refreshIcon = document.getElementById('refreshIcon');
    if (refreshIcon) refreshIcon.classList.add('spin');

    const progressContainer = document.getElementById('progressContainer');
    const progressBarFill = document.getElementById('progressBarFill');
    const progressStatusText = document.getElementById('progressStatusText');
    const progressPercentText = document.getElementById('progressPercentText');

    progressContainer.style.display = 'block';
    progressBarFill.style.width = '25%';
    progressPercentText.textContent = '25%';
    progressStatusText.innerHTML = '<i data-lucide="loader-2" class="spin"></i> Polling followed sources &amp; running Whisper transcription...';
    lucide.createIcons();

    try {
        const resp = await fetch('/refresh', { method: 'POST' });
        const data = await resp.json();

        if (!resp.ok) throw new Error(data.detail || 'Manual refresh failed');

        const newCount = data.new_items_count || 0;
        progressBarFill.style.width = '100%';
        progressPercentText.textContent = '100%';
        progressStatusText.innerHTML = `<i data-lucide="check" style="color: #10b981;"></i> Checked ${data.sources_checked} sources. ${newCount} new dispatches found!`;
        lucide.createIcons();

        if (newCount > 0) {
            const newsResp = await fetch('/newspaper?limit=20');
            const newsData = await newsResp.json();
            if (newsData.items && newsData.items.length > 0) {
                loadArticles(newsData.items);
            }
            showToast(`Fetched & synthesized ${newCount} new dispatches!`);
        } else {
            showToast(`All followed sources are up to date! (0 new items since last visit).`);
        }

        setTimeout(() => {
            progressContainer.style.display = 'none';
        }, 2000);

    } catch (err) {
        console.error('Refresh error:', err);
        showToast(err.message || 'Refresh failed', 'error');
        progressContainer.style.display = 'none';
    } finally {
        if (refreshIcon) refreshIcon.classList.remove('spin');
    }
}

// ==========================================================================
// ARTICLES DATA PROCESSOR & RENDERER
// ==========================================================================

function loadArticles(articlesList) {
    state.articles = articlesList.map((art, idx) => {
        const text = art.text || "";
        const words = text.trim().split(/\s+/).length;
        const readTime = Math.max(1, Math.ceil(words / 220));

        let deck = art.deck;
        if (!deck) {
            const firstPeriod = text.indexOf('.');
            if (firstPeriod > 20 && firstPeriod < 180) {
                deck = text.slice(0, firstPeriod + 1);
            } else {
                deck = text.slice(0, 140) + '...';
            }
        }

        const summary = art.summary || (text.slice(0, 350) + "...");
        const takeaways = art.takeaways && art.takeaways.length > 0 ? art.takeaways : [
            summary.slice(0, 120) + "...",
            "In-depth analysis and reporting extracted by Backstory engine"
        ];

        let img = art.thumbnail_url || art.image_url || DEFAULT_IMAGES[idx % DEFAULT_IMAGES.length];
        
        // YouTube video detection
        const isVideo = art.is_video || (art.url && (art.url.includes('youtube.com') || art.url.includes('youtu.be')));
        let videoId = art.video_id;
        if (!videoId && isVideo && art.url) {
            const match = art.url.match(/(?:v=|\/embed\/|\/17\/|youtu\.be\/|\/v\/|\/e\/|watch\?v=)([^#&?]*).*/);
            if (match && match[1] && match[1].length === 11) {
                videoId = match[1];
                if (!art.thumbnail_url) {
                    img = `https://img.youtube.com/vi/${videoId}/hqdefault.jpg`;
                }
            }
        }

        return {
            ...art,
            id: `art-${idx}`,
            deck: deck,
            summary: summary,
            takeaways: takeaways,
            words: words,
            read_time: readTime,
            image_url: img,
            is_video: isVideo,
            video_id: videoId,
            category: art.category || getCategoryFromText(art.title + " " + text),
        };
    });

    const countBadge = document.getElementById('articleCountBadge');
    if (countBadge) countBadge.textContent = `${state.articles.length} DISPATCHES`;

    const totalReadMins = state.articles.reduce((sum, a) => sum + (a.read_time || 2), 0);
    const readDisplay = document.getElementById('readingTimeDisplay');
    if (readDisplay) readDisplay.textContent = `${totalReadMins} MIN READ`;

    renderBroadsheetGrid(state.articles);
    renderNewsletterView(state.articles);
    renderRawJsonView(state.articles);

    const ticker = document.getElementById('tickerText');
    if (ticker && state.articles.length > 0) {
        const headlines = state.articles.map(a => a.title).join(' • ');
        ticker.textContent = `HEADLINES: ${headlines}`;
    }

    lucide.createIcons();
}

function getCategoryFromText(str) {
    const lower = (str || "").toLowerCase();
    if (lower.includes('church') || lower.includes('faith') || lower.includes('god') || lower.includes('worship')) return 'Faith & Community';
    if (lower.includes('batman') || lower.includes('comic') || lower.includes('superhero') || lower.includes('film')) return 'Comics & Entertainment';
    if (lower.includes('ai') || lower.includes('neural') || lower.includes('model') || lower.includes('software') || lower.includes('code') || lower.includes('silicon')) return 'Technology & AI';
    if (lower.includes('market') || lower.includes('bank') || lower.includes('economy') || lower.includes('dollar') || lower.includes('trade')) return 'Economy & Markets';
    if (lower.includes('climate') || lower.includes('energy') || lower.includes('treaty') || lower.includes('summit')) return 'Global Affairs';
    if (lower.includes('culture') || lower.includes('art') || lower.includes('book') || lower.includes('philosophy')) return 'Culture & Ideas';
    return 'General Dispatch';
}

// ==========================================================================
// BROADSHEET NEWSPAPER RENDERER
// ==========================================================================

function renderBroadsheetGrid(articles) {
    const grid = document.getElementById('broadsheetGrid');
    if (!grid) return;

    if (articles.length === 0) {
        grid.innerHTML = `<div style="grid-column: 1 / -1; text-align: center; padding: 4rem; font-style: italic; color: var(--ink-muted);">No articles loaded. Enter a URL or click "Fetch What's New" above.</div>`;
        return;
    }

    const leadArticle = articles[0];
    const secondaryArticle = articles[1] || null;
    const sidebarArticles = articles.slice(2);

    const paragraphs = leadArticle.text.split('\n\n').filter(p => p.trim().length > 0);
    const col1Text = paragraphs.slice(0, 2).map(p => `<p>${escapeHtml(p)}</p>`).join('');
    const col2Text = paragraphs.slice(2).map(p => `<p>${escapeHtml(p)}</p>`).join('');

    grid.innerHTML = `
        <!-- Left Main Broadsheet Column -->
        <div class="broadsheet-main">

            <!-- 1. Lead Hero Story -->
            <article class="lead-story">
                <div class="lead-kicker">
                    <i data-lucide="flame" style="width: 14px; height: 14px;"></i>
                    <span>${escapeHtml(leadArticle.category)} • ${leadArticle.read_time} MIN READ</span>
                    ${leadArticle.is_video ? `<span class="video-badge"><i data-lucide="video" style="width: 11px; height: 11px;"></i> Video Briefing</span>` : ''}
                </div>

                <h1 class="lead-headline" onclick="openReaderModal('${leadArticle.id}')">
                    ${escapeHtml(leadArticle.title)}
                </h1>

                <div class="lead-deck">
                    ${escapeHtml(leadArticle.deck)}
                </div>

                <div class="story-byline-bar">
                    <span>${escapeHtml(leadArticle.author || "By Staff Correspondent")}</span>
                    <span class="byline-dot">•</span>
                    <span>${escapeHtml(leadArticle.published_date || "Today")}</span>
                    <span class="byline-dot">•</span>
                    <span>${leadArticle.extraction_method || 'Trafilatura'}</span>
                </div>

                <!-- Cross-Source Deduplication Banner if present -->
                ${renderCrossSourceBanner(leadArticle)}

                <!-- Split Layout: Hero Image / Video + Columnar Text -->
                <div class="lead-content-layout">
                    <div class="lead-media-col">
                        <div class="editorial-media">
                            <div class="${leadArticle.is_video ? 'video-thumbnail-wrap' : ''}" onclick="openReaderModal('${leadArticle.id}')">
                                <img src="${leadArticle.image_url}" alt="Hero Editorial Media" class="editorial-media-img">
                                ${leadArticle.is_video ? `<div class="video-play-icon"><i data-lucide="play" style="width: 20px; height: 20px; margin-left: 2px;"></i></div>` : ''}
                            </div>
                            <div class="media-caption">
                                ${escapeHtml(leadArticle.image_caption || leadArticle.title)}
                            </div>
                        </div>

                        <!-- Special Dark Callout Box -->
                        <div class="editorial-callout-box">
                            <div class="callout-icon-wrap">
                                ${leadArticle.is_video ? '▶' : '✝'}
                            </div>
                            <div class="callout-content">
                                <h4>${escapeHtml(leadArticle.callout_title || "Executive Briefing:")}</h4>
                                <p>${escapeHtml(leadArticle.summary || leadArticle.callout_text || leadArticle.deck)}</p>
                            </div>
                        </div>
                    </div>

                    <div class="lead-text-col">
                        <div class="editorial-text drop-cap">
                            ${col1Text || `<p>${escapeHtml(leadArticle.text)}</p>`}
                        </div>
                        ${col2Text ? `<div class="editorial-text">${col2Text}</div>` : ''}
                    </div>
                </div>
            </article>

            <!-- 2. Secondary Bottom Story Strip -->
            ${secondaryArticle ? `
                <article class="secondary-story-strip">
                    <div class="${secondaryArticle.is_video ? 'video-thumbnail-wrap' : ''}" style="width: 140px; height: 95px; flex-shrink: 0;" onclick="openReaderModal('${secondaryArticle.id}')">
                        <img src="${secondaryArticle.image_url}" alt="Thumbnail" class="strip-thumbnail" style="width: 100%; height: 100%; object-fit: cover;">
                        ${secondaryArticle.is_video ? `<div class="video-play-icon" style="width: 30px; height: 30px;"><i data-lucide="play" style="width: 14px; height: 14px; margin-left: 1px;"></i></div>` : ''}
                    </div>
                    <div class="strip-content">
                        <div style="display: flex; align-items: center; gap: 6px; margin-bottom: 3px;">
                            ${secondaryArticle.is_video ? `<span class="video-badge"><i data-lucide="video" style="width: 10px; height: 10px;"></i> Video</span>` : ''}
                            <span class="strip-highlight-tag">${escapeHtml(secondaryArticle.highlight_tag || secondaryArticle.category)}</span>
                        </div>
                        <h3 onclick="openReaderModal('${secondaryArticle.id}')">${escapeHtml(secondaryArticle.title)}</h3>
                        <div class="strip-byline">
                            ${escapeHtml(secondaryArticle.author || "Staff")} • ${escapeHtml(secondaryArticle.published_date || "Recent")}
                        </div>
                        <p class="strip-text">
                            ${escapeHtml(secondaryArticle.summary || secondaryArticle.deck)}
                        </p>
                        ${renderCrossSourceBanner(secondaryArticle)}
                    </div>
                </article>
            ` : ''}
        </div>

        <!-- Right Broadsheet Sidebar -->
        <aside class="broadsheet-sidebar">
            <div class="sidebar-section-header">
                <i data-lucide="bookmark" style="width: 14px; height: 14px;"></i>
                <span>Key Columns &amp; Video Dispatches</span>
            </div>

            ${sidebarArticles.length > 0 ? sidebarArticles.map(art => `
                <article class="sidebar-story">
                    <div style="display: flex; align-items: center; gap: 6px; margin-bottom: 4px;">
                        ${art.is_video ? `<span class="video-badge"><i data-lucide="video" style="width: 10px; height: 10px;"></i> Video</span>` : ''}
                        <span style="font-size: 0.72rem; text-transform: uppercase; color: var(--ink-accent); font-weight: 700; font-family: var(--font-sans);">${escapeHtml(art.category)}</span>
                    </div>

                    <h4 onclick="openReaderModal('${art.id}')">${escapeHtml(art.title)}</h4>
                    
                    <div class="${art.is_video ? 'video-thumbnail-wrap' : ''}" onclick="openReaderModal('${art.id}')">
                        <img src="${art.image_url}" alt="Sidebar Media" class="sidebar-story-img">
                        ${art.is_video ? `<div class="video-play-icon" style="width: 36px; height: 36px;"><i data-lucide="play" style="width: 16px; height: 16px; margin-left: 1px;"></i></div>` : ''}
                    </div>
                    
                    ${art.pull_quote ? `
                        <div class="pull-quote">${escapeHtml(art.pull_quote)}</div>
                    ` : ''}

                    <div class="sidebar-story-text editorial-text">
                        <p><strong>Executive Summary:</strong> ${escapeHtml(art.summary || art.deck)}</p>
                    </div>

                    ${renderCrossSourceBanner(art)}
                </article>
            `).join('') : `
                <article class="sidebar-story">
                    <h4>Executive Summary Brief</h4>
                    <p class="sidebar-story-text">
                        ${escapeHtml(leadArticle.summary || "All extracted text & video transcripts are synthesized and organized into structured broadsheet briefings.")}
                    </p>
                    <div class="pull-quote">
                        “Synthesizing information into clear, calm, actionable daily digests.”
                    </div>
                    <img src="https://images.unsplash.com/photo-1585829365295-ab7cd400c167?w=400&auto=format&fit=crop&q=80" alt="Newspaper" class="sidebar-story-img">
                </article>
            `}
        </aside>
    `;
}

function renderCrossSourceBanner(art) {
    if (!art.related_sources || art.related_sources.length <= 1) {
        if (!art.cross_source_count || art.cross_source_count <= 1) return '';
    }

    const sources = art.related_sources || [];
    const count = art.cross_source_count || sources.length;

    return `
        <div class="cross-source-banner">
            <div class="cross-source-banner-header">
                <i data-lucide="layers" style="width: 14px; height: 14px; color: var(--accent-gold);"></i>
                <span>Cross-Source Consensus: Covered by ${count} followed sources</span>
            </div>
            ${sources.length > 0 ? `
                <div class="cross-source-links">
                    ${sources.map(s => `
                        <a href="${s.url}" target="_blank" rel="noopener noreferrer" class="source-pill" title="${escapeHtml(s.title || s.url)}">
                            <i data-lucide="${s.source_type && s.source_type.includes('youtube') ? 'video' : 'globe'}" style="width: 11px; height: 11px;"></i>
                            <span>${escapeHtml(s.title ? s.title.slice(0, 30) + '...' : s.url.replace(/^https?:\/\/(www\.)?/, '').slice(0, 20))}</span>
                        </a>
                    `).join('')}
                </div>
            ` : ''}
        </div>
    `;
}

// ==========================================================================
// NEWSLETTER VIEW RENDERER (Processed Newsletter Format)
// ==========================================================================

function renderNewsletterView(articles) {
    const list = document.getElementById('newsletterArticlesList');
    const execSummaryList = document.getElementById('execSummaryList');
    if (!list) return;

    if (articles.length === 0) {
        list.innerHTML = `<p style="text-align: center; color: var(--ink-muted);">No articles available.</p>`;
        return;
    }

    // Build Executive Takeaways at the top
    if (execSummaryList) {
        execSummaryList.innerHTML = articles.map(art => `
            <li style="margin-bottom: 0.5rem;">
                <strong>${escapeHtml(art.category)}:</strong> ${escapeHtml(art.deck || art.title)}
                ${art.cross_source_count > 1 ? `<span style="font-size: 0.75rem; color: var(--accent-gold); font-weight: 600;"> (${art.cross_source_count} sources)</span>` : ''}
            </li>
        `).join('');
    }

    // Build Newsletter Story Blocks with Summaries & Takeaway Checklists
    list.innerHTML = articles.map(art => `
        <article class="newsletter-article-item">
            <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 0.5rem;">
                <span class="newsletter-category-pill">${escapeHtml(art.category)}</span>
                ${art.is_video ? `<span class="video-badge"><i data-lucide="video" style="width: 11px; height: 11px;"></i> YouTube Video</span>` : ''}
            </div>

            <h2 class="newsletter-item-title" onclick="openReaderModal('${art.id}')">${escapeHtml(art.title)}</h2>
            <div class="newsletter-item-meta">
                ${escapeHtml(art.author || "Editorial Staff")} • ${escapeHtml(art.published_date || "Today")} • ${art.read_time} min read
            </div>
            
            <p class="newsletter-item-deck" style="font-family: var(--font-headline); font-size: 1.1rem; font-weight: 600; color: var(--ink-primary); margin-bottom: 0.75rem;">
                ${escapeHtml(art.deck)}
            </p>

            <div class="newsletter-item-prose">
                <p><strong>Executive Synthesis:</strong> ${escapeHtml(art.summary)}</p>
            </div>

            ${renderCrossSourceBanner(art)}

            ${art.takeaways && art.takeaways.length > 0 ? `
                <div style="background-color: var(--bg-paper-alt); border-left: 3px solid var(--ink-accent); padding: 0.85rem 1rem; border-radius: var(--border-radius-sm); margin: 1rem 0;">
                    <strong style="font-family: var(--font-sans); font-size: 0.82rem; text-transform: uppercase; color: var(--ink-accent); display: block; margin-bottom: 0.4rem;">
                        Key Takeaways:
                    </strong>
                    <ul style="padding-left: 1.25rem; font-size: 0.92rem; color: var(--ink-secondary); line-height: 1.5;">
                        ${art.takeaways.map(t => `<li>${escapeHtml(t)}</li>`).join('')}
                    </ul>
                </div>
            ` : ''}

            <button type="button" class="newsletter-read-btn" onclick="openReaderModal('${art.id}')">
                ${art.is_video ? 'Watch Video & Read Full Transcript' : 'Read Full Extracted Dispatch'} <i data-lucide="arrow-right" style="width: 14px; height: 14px;"></i>
            </button>
        </article>
    `).join('');

    lucide.createIcons();
}

// ==========================================================================
// RAW JSON VIEW RENDERER
// ==========================================================================

function renderRawJsonView(articles) {
    const display = document.getElementById('rawJsonDisplay');
    if (!display) return;
    display.textContent = JSON.stringify(articles, null, 2);
}

// ==========================================================================
// FOCUSED ARTICLE READER MODAL & TEXT-TO-SPEECH
// ==========================================================================

function initReaderModal() {
    const closeBtn = document.getElementById('closeReaderBtn');
    const modal = document.getElementById('readerModal');
    const copyBtn = document.getElementById('modalCopyBtn');
    const zoomBtn = document.getElementById('zoomInBtn');
    const ttsBtn = document.getElementById('ttsAudioBtn');

    if (closeBtn && modal) {
        closeBtn.addEventListener('click', closeReaderModal);
        modal.addEventListener('click', (e) => {
            if (e.target === modal) closeReaderModal();
        });
    }

    if (copyBtn) {
        copyBtn.addEventListener('click', () => {
            const prose = document.getElementById('modalText').innerText;
            navigator.clipboard.writeText(prose).then(() => {
                showToast('Article text copied to clipboard!');
            });
        });
    }

    if (zoomBtn) {
        zoomBtn.addEventListener('click', () => {
            state.fontSizeLevel = (state.fontSizeLevel + 1) % 3;
            const prose = document.getElementById('modalText');
            const sizes = ['1.1rem', '1.3rem', '1.5rem'];
            prose.style.fontSize = sizes[state.fontSizeLevel];
        });
    }

    if (ttsBtn) {
        ttsBtn.addEventListener('click', toggleTTS);
    }

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            closeReaderModal();
            const sm = document.getElementById('sourcesModal');
            if (sm) sm.style.display = 'none';
        }
    });
}

function openReaderModal(articleId) {
    const article = state.articles.find(a => a.id === articleId);
    if (!article) return;

    document.getElementById('modalTitle').textContent = article.title;
    document.getElementById('modalByline').textContent = `${article.author || "Staff"} • ${article.published_date || "Recent"} • ${article.read_time} MIN READ`;
    document.getElementById('modalCategory').textContent = article.category;
    document.getElementById('modalSourceBadge').textContent = article.extraction_method || "Direct";
    
    // Video player embedding
    const videoEmbed = document.getElementById('modalVideoEmbed');
    const videoIframe = document.getElementById('modalVideoIframe');
    if (article.is_video && article.video_id) {
        if (videoEmbed && videoIframe) {
            videoIframe.src = `https://www.youtube-nocookie.com/embed/${article.video_id}?autoplay=0`;
            videoEmbed.style.display = 'block';
        }
    } else {
        if (videoEmbed && videoIframe) {
            videoEmbed.style.display = 'none';
            videoIframe.src = '';
        }
    }

    const paragraphs = article.text.split('\n\n').filter(p => p.trim().length > 0);
    const html = `
        <div style="background-color: var(--bg-paper-alt); border-left: 4px solid var(--accent-gold); padding: 1rem 1.25rem; margin-bottom: 1.5rem; border-radius: var(--border-radius-sm);">
            <strong style="display: block; font-family: var(--font-sans); font-size: 0.85rem; text-transform: uppercase; color: var(--ink-primary); margin-bottom: 0.35rem;">
                Executive Newsletter Summary:
            </strong>
            <p style="font-size: 1rem; line-height: 1.5; color: var(--ink-secondary); margin-bottom: 0.5rem;">
                ${escapeHtml(article.summary)}
            </p>
            ${article.takeaways && article.takeaways.length > 0 ? `
                <ul style="padding-left: 1.2rem; font-size: 0.9rem; color: var(--ink-muted);">
                    ${article.takeaways.map(t => `<li>${escapeHtml(t)}</li>`).join('')}
                </ul>
            ` : ''}
        </div>
        ${renderCrossSourceBanner(article)}
        ${paragraphs.map(p => `<p>${escapeHtml(p)}</p>`).join('')}
    `;
    document.getElementById('modalText').innerHTML = html;

    const originalLink = document.getElementById('modalOriginalLink');
    if (originalLink) {
        originalLink.href = article.url || "#";
        originalLink.style.display = article.url && !article.url.startsWith('pasted://') ? 'inline-flex' : 'none';
    }

    const modal = document.getElementById('readerModal');
    if (modal) {
        modal.style.display = 'flex';
        document.body.style.overflow = 'hidden';
    }

    lucide.createIcons();
}

function closeReaderModal() {
    const modal = document.getElementById('readerModal');
    if (modal) {
        modal.style.display = 'none';
        document.body.style.overflow = 'auto';
    }
    const videoIframe = document.getElementById('modalVideoIframe');
    if (videoIframe) videoIframe.src = '';
    stopTTS();
}

function toggleTTS() {
    if (state.isSpeaking) {
        stopTTS();
    } else {
        const text = document.getElementById('modalText').innerText;
        if (!text || !('speechSynthesis' in window)) {
            showToast('Text-to-speech not supported in this browser.', 'error');
            return;
        }
        state.synthUtterance = new SpeechSynthesisUtterance(text);
        state.synthUtterance.rate = 1.0;
        state.synthUtterance.onend = () => {
            state.isSpeaking = false;
            updateTTSIcon(false);
        };
        window.speechSynthesis.speak(state.synthUtterance);
        state.isSpeaking = true;
        updateTTSIcon(true);
        showToast('Reading article aloud...');
    }
}

function stopTTS() {
    if ('speechSynthesis' in window) {
        window.speechSynthesis.cancel();
    }
    state.isSpeaking = false;
    updateTTSIcon(false);
}

function updateTTSIcon(speaking) {
    const btn = document.getElementById('ttsAudioBtn');
    if (!btn) return;
    if (speaking) {
        btn.innerHTML = '<i data-lucide="volume-x" style="color: #ef4444;"></i>';
    } else {
        btn.innerHTML = '<i data-lucide="volume-2"></i>';
    }
    lucide.createIcons();
}

// ==========================================================================
// EXPORT & UTILITIES
// ==========================================================================

function initPrintAndCopy() {
    const printBtn = document.getElementById('printPdfBtn');
    if (printBtn) {
        printBtn.addEventListener('click', () => {
            window.print();
        });
    }

    const copyNlBtn = document.getElementById('copyNewsletterBtn');
    if (copyNlBtn) {
        copyNlBtn.addEventListener('click', () => {
            const formatted = state.articles.map(a => 
                `📰 **${a.title}**\n*${a.category} | By ${a.author || "Staff"}*\n\n**Deck:** ${a.deck}\n\n**Executive Summary:**\n${a.summary}\n\n**Key Takeaways:**\n${(a.takeaways || []).map(t => `• ${t}`).join('\n')}\n\n🔗 ${a.url}\n`
            ).join('\n---\n\n');

            navigator.clipboard.writeText(formatted).then(() => {
                showToast('Newsletter summary copied to clipboard!');
            });
        });
    }

    const copyJsonBtn = document.getElementById('copyJsonBtn');
    if (copyJsonBtn) {
        copyJsonBtn.addEventListener('click', () => {
            const jsonText = JSON.stringify(state.articles, null, 2);
            navigator.clipboard.writeText(jsonText).then(() => {
                showToast('JSON payload copied!');
            });
        });
    }
}

function showToast(message, type = 'info') {
    const container = document.getElementById('toastContainer');
    if (!container) return;

    const toast = document.createElement('div');
    toast.className = 'toast';
    const icon = type === 'error' ? 'alert-circle' : 'check';
    toast.innerHTML = `<i data-lucide="${icon}"></i> <span>${escapeHtml(message)}</span>`;
    container.appendChild(toast);
    lucide.createIcons();

    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateY(10px)';
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}

function escapeHtml(str) {
    if (!str) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}
