#  QuickSight RLS 

This cloudformation will deploy Lambda code that will generate RLS rules based on OU tags. 
Will create a Athena table based on the CSV rules in S3, create QuickSight DataSource and QuikcSight DataSet 


##  RLS Generator and RLS dataset management 
Generate RLS csv file for QuickSight based on AWS Organizational Units. 

[About QuickSight RLS](https://docs.aws.amazon.com/quicksight/latest/user/restrict-access-to-a-data-set-using-row-level-security.html)
[About AWS Organizational Unit ](https://docs.aws.amazon.com/organizations/latest/userguide/orgs_introduction.html)


## Defining TAGS

1) Tags at root OU level, Give full access to all data and overwrite any other rules for user at other levels.
2) Tags at OU level will be Inherited TAG to all children accounts.
2) Tags at Account level will be generated rules for Account level.


## Output 
Output is  uploaded to `BUCKET_NAME`.


## Example Output 
```
UserName,GroupName,account_id,payer_id
user_with_wildcard_access,,,
user_with_acces_of_all_acounts_of_single_payer,,000111222333
cross_ou_user,,"0140000000,7200000,74700000,853000000",
,group1,"0140000000,7200000",
,group_accessa_all,,
```
