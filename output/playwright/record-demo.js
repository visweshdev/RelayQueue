async page => {
 await page.goto('http://localhost:8000/');
 await page.setViewportSize({width:1440,height:1000});
 await page.getByRole('button',{name:'Try local demo',exact:true}).click();
 await page.getByText('Workspace connected',{exact:true}).waitFor();
 await page.locator('nav a[href="#upload"]').click();
 await page.getByRole('button',{name:'Use sample data',exact:true}).click();
 await page.getByText('Sample sales.csv selected',{exact:true}).waitFor();
 await page.getByRole('button',{name:'Create report',exact:true}).click();
 await page.locator('#result-summary').filter({hasText:'50.10'}).waitFor();
 await page.waitForTimeout(3000);
 await page.getByRole('button',{name:'Done',exact:true}).click();
 await page.locator('nav a[href="#jobs"]').click();
 await page.locator('.job-link').first().waitFor();
 await page.waitForTimeout(1500);
}
