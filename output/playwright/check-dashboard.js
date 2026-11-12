async page => { await page.setViewportSize({width:390,height:844});
 await page.getByLabel('Access key').fill('dev-key-1');
 await page.getByRole('button', {name:'Connect',exact:true}).click();
 await page.getByText('Local operator',{exact:true}).waitFor();
 if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)) throw new Error('Mobile overflow');
 await page.screenshot({path:'output/playwright/dashboard-mobile.png', fullPage:true});
 await page.setViewportSize({width:1440,height:1000});
 await page.getByLabel('Sales CSV').setInputFiles('examples/sales.csv');
 await page.getByRole('button',{name:'Submit report',exact:true}).click();
 await page.locator('#result').filter({hasText:'50.10'}).waitFor();
 await page.screenshot({path:'output/playwright/dashboard.png',fullPage:true});
}
