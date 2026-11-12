async page => {
 await page.setViewportSize({width:390,height:844});
 await page.locator('nav a[href="#upload"]').click();
 await page.screenshot({path:'output/playwright/dashboard-mobile.png',fullPage:true});
 if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth))throw Error('Mobile overflow');
 await page.setViewportSize({width:1440,height:1000});
 await page.locator('nav a[href="#jobs"]').click();
}
