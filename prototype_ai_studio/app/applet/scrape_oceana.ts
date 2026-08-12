import * as cheerio from 'cheerio';

async function testScrapeOceana() {
  try {
    const res = await fetch('https://oceana.org/campaigns/');
    const html = await res.text();
    const $ = cheerio.load(html);
    
    const projects: any[] = [];
    $('a').each((i, el) => {
      const url = $(el).attr('href');
      const title = $(el).text().trim();
      if (url && url.includes('/campaigns/') && title && title.length > 5 && !url.endsWith('/campaigns/')) {
        projects.push({ title, url });
      }
    });
    
    console.log(JSON.stringify(projects.slice(0, 10), null, 2));
  } catch (e) {
    console.error(e);
  }
}

testScrapeOceana();
