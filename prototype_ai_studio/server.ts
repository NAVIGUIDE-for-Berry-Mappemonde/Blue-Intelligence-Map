import express from "express";
import { createServer as createViteServer } from "vite";
import * as cheerio from "cheerio";
import { GoogleGenAI, Type } from "@google/genai";

const ai = new GoogleGenAI({ apiKey: process.env.GEMINI_API_KEY });

async function geocode(query: string): Promise<[number, number] | null> {
  try {
    // Add a small delay to respect Nominatim's rate limit (1 req/s)
    await new Promise(resolve => setTimeout(resolve, 1000));
    const url = `https://nominatim.openstreetmap.org/search?q=${encodeURIComponent(query)}&format=json&limit=1`;
    const res = await fetch(url, {
      headers: {
        'User-Agent': 'BlueIntelligenceScraper/1.0 (contact@example.com)'
      }
    });
    const data = await res.json() as any[];
    if (data && data.length > 0) {
      return [parseFloat(data[0].lon), parseFloat(data[0].lat)];
    }
  } catch (e) {
    console.error(`Geocoding failed for ${query}`);
  }
  return null;
}

function hashString(str: string): number {
  let hash = 0;
  for (let i = 0; i < str.length; i++) {
    hash = ((hash << 5) - hash) + str.charCodeAt(i);
    hash |= 0;
  }
  return Math.abs(hash);
}

function getOceanCoordinates(title: string): [number, number] {
  const hash = hashString(title);
  
  // Define major ocean bounding boxes [minLon, maxLon, minLat, maxLat]
  const oceanRegions = [
    [-170, -110, -30, 30], // Pacific Ocean
    [-50, -20, -30, 30],   // Atlantic Ocean
    [60, 90, -30, 10],     // Indian Ocean
    [140, 170, -30, 10]    // Western Pacific
  ];
  
  const region = oceanRegions[hash % oceanRegions.length];
  
  // Use the hash to pick a deterministic point within the region
  const lon = region[0] + (hash % 100) / 100 * (region[1] - region[0]);
  const lat = region[2] + ((hash >> 2) % 100) / 100 * (region[3] - region[2]);
  
  return [lon, lat];
}

async function extractProjectDetailsWithAI(title: string, projectUrl: string, funder: string): Promise<{ description: string, location: string }> {
  try {
    const res = await fetch(projectUrl);
    const html = await res.text();
    const $ = cheerio.load(html);
    
    let textContent = $('body').text().replace(/\s+/g, ' ').trim();
    
    let externalUrl = '';
    $('a').each((i, el) => {
      const linkText = $(el).text().toLowerCase();
      const href = $(el).attr('href');
      if (href && href.startsWith('http') && !href.includes('oceanfdn.org') && !href.includes('oceana.org')) {
        if (linkText.includes('website') || linkText.includes('visit') || $(el).hasClass('website-link')) {
          externalUrl = href;
        }
      }
    });

    if (externalUrl) {
      try {
        const extRes = await fetch(externalUrl, { signal: AbortSignal.timeout(3000) });
        const extHtml = await extRes.text();
        const $ext = cheerio.load(extHtml);
        textContent += " " + $ext('body').text().replace(/\s+/g, ' ').trim();
      } catch (e) {
        console.log(`Failed to scrape external URL: ${externalUrl}`);
      }
    }

    const limitedText = textContent.substring(0, 6000);

    const response = await ai.models.generateContent({
      model: "gemini-3-flash-preview",
      contents: `Analyze the following text about a marine conservation project named "${title}".
      
      Text:
      ${limitedText}
      
      Provide a JSON response with:
      1. "description": A concise, single-sentence description explaining the specific purpose, goal, or action of the project. Do NOT repeat the project title ("${title}") or variations of it. Do NOT include boilerplate text like "Hosted Projects Our Mission:" or "Our Mission:". Focus entirely on WHAT the project does and WHY it exists.
      2. "location": The most specific geographic location mentioned (e.g., a specific country, region, ocean, or city). If the project is global or no specific location is mentioned, return "Global".`,
      config: {
        responseMimeType: "application/json",
        responseSchema: {
          type: Type.OBJECT,
          properties: {
            description: { type: Type.STRING },
            location: { type: Type.STRING }
          },
          required: ["description", "location"]
        }
      }
    });

    const result = JSON.parse(response.text || "{}");
    return {
      description: result.description || `A marine conservation initiative dedicated to protecting ocean ecosystems and supporting sustainable practices.`,
      location: result.location || "Global"
    };
  } catch (error) {
    console.error(`AI extraction failed for ${title}:`, error);
    return {
      description: `A marine conservation initiative dedicated to protecting ocean ecosystems and supporting sustainable practices.`,
      location: "Global"
    };
  }
}

// In-memory cache to avoid re-scraping on every request
let cachedGeoJSON: any = null;
let scrapePromise: Promise<any> | null = null;

async function scrapeProjects() {
  if (cachedGeoJSON) return cachedGeoJSON;
  if (scrapePromise) return scrapePromise;
  
  scrapePromise = (async () => {
    const features: any[] = [];
    
    try {
      // 1. Scrape The Ocean Foundation
      console.log("Scraping The Ocean Foundation...");
      const tofRes = await fetch("https://oceanfdn.org/projects/");
      const tofHtml = await tofRes.text();
      const $tof = cheerio.load(tofHtml);
      
      const tofProjects: any[] = [];
      $tof('a').each((i, el) => {
        const title = $tof(el).text().trim();
        const url = $tof(el).attr('href');
        if (title && title.length > 5 && url && url.includes('/projects/') && !url.endsWith('/projects/')) {
          // Avoid duplicates
          if (!tofProjects.find(p => p.url === url)) {
            tofProjects.push({ title, url, funder: "The Ocean Foundation" });
          }
        }
      });

      // 2. Scrape Oceana
      console.log("Scraping Oceana...");
      const oceanaRes = await fetch("https://oceana.org/campaigns/");
      const oceanaHtml = await oceanaRes.text();
      const $oceana = cheerio.load(oceanaHtml);
      
      const oceanaProjects: any[] = [];
      $oceana('a').each((i, el) => {
        const title = $oceana(el).text().trim();
        const url = $oceana(el).attr('href');
        if (title && title.length > 5 && url && url.includes('/campaigns/') && !url.endsWith('/campaigns/')) {
          if (!oceanaProjects.find(p => p.url === url)) {
            oceanaProjects.push({ title, url, funder: "Oceana" });
          }
        }
      });

      const allProjects = [...tofProjects, ...oceanaProjects];
      
      // We will process them in chunks of 3 to avoid rate limits
      const chunkSize = 3;
      for (let i = 0; i < allProjects.length; i += chunkSize) {
        const chunk = allProjects.slice(i, i + chunkSize);
        console.log(`Processing chunk ${i / chunkSize + 1} of ${Math.ceil(allProjects.length / chunkSize)}...`);
        
        const chunkPromises = chunk.map(async (proj) => {
          let projectUrl = proj.url;
          if (projectUrl.startsWith('/')) {
            projectUrl = proj.funder === "The Ocean Foundation" 
              ? `https://oceanfdn.org${projectUrl}`
              : `https://oceana.org${projectUrl}`;
          }

          const aiDetails = await extractProjectDetailsWithAI(proj.title, projectUrl, proj.funder);
          
          let coords: [number, number] | null = null;
          if (aiDetails.location && aiDetails.location !== "Global") {
            coords = await geocode(aiDetails.location);
          }
          if (!coords) {
            coords = await geocode(proj.title);
          }
          if (!coords) {
            coords = getOceanCoordinates(proj.title);
          }
          
          return {
            type: "Feature",
            geometry: { type: "Point", coordinates: coords },
            properties: {
              title: proj.title,
              url: projectUrl,
              funder: proj.funder,
              description: aiDetails.description,
              location: aiDetails.location,
              image: "https://images.unsplash.com/photo-1582967788606-a171c1080cb0?auto=format&fit=crop&w=800&q=80"
            }
          };
        });
        
        const chunkResults = await Promise.all(chunkPromises);
        features.push(...chunkResults);
        
        // Add a small delay between chunks to avoid rate limits
        if (i + chunkSize < allProjects.length) {
          await new Promise(resolve => setTimeout(resolve, 1500));
        }
      }
      
      cachedGeoJSON = {
        type: "FeatureCollection",
        features
      };
      
      console.log(`Scraping complete. Found ${features.length} projects.`);
    } catch (error) {
      console.error("Scraping error:", error);
      cachedGeoJSON = { type: "FeatureCollection", features: [] };
    } finally {
      scrapePromise = null;
    }
    
    return cachedGeoJSON;
  })();
  
  return scrapePromise;
}

async function startServer() {
  const app = express();
  const PORT = 3000;

  // Trigger initial scrape in the background
  scrapeProjects();

  // API routes FIRST
  app.get("/api/projects", async (req, res) => {
    try {
      const data = await scrapeProjects();
      res.json(data);
    } catch (error) {
      console.error("Global Retrieval Error:", error);
      res.status(500).json({ error: "Failed to retrieve data from external sources" });
    }
  });

  // Vite middleware for development
  if (process.env.NODE_ENV !== "production") {
    const vite = await createViteServer({
      server: { middlewareMode: true },
      appType: "spa",
    });
    app.use(vite.middlewares);
  } else {
    app.use(express.static('dist'));
  }

  app.listen(PORT, "0.0.0.0", () => {
    console.log(`Server running on http://localhost:${PORT}`);
  });
}

startServer();
