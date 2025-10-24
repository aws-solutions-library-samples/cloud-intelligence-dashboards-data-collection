def parse_granular_config(data_string):
    """Create policy dictionaries from a string with comma-separated values.
    
    Format: module,policy_type,principal,regions,payload
    Regions are separated by colons within the regions field.
    Multiple lines are separated by linebreaks.
    
    Returns a list of policy dictionaries.
    """
    instances = []
    lines = data_string.strip().split('\n')
    
    for line in lines:
        line = line.strip()
        if not line:  # Skip empty lines
            continue
            
        parts = line.split(',')
        if len(parts) < 3:
            continue # malformed so ignore
        while len(parts) < 5:
            parts.append(None)
        
        module, policy_type, principal, regions_str, payload = parts
        
        # Parse regions (colon-separated)
        regions = regions_str.split(':') if regions_str else []
        
        instance = {
            'principal': principal,
            'module': module,
            'policy_type': policy_type,
            'regions': regions,
            'payload': payload
        }
        instances.append(instance)
    
    return instances

import boto3
import re
from collections import OrderedDict


class OrganizationsPrincipalExpander:
    """Expands OU principals to individual account principals using AWS Organizations."""
    
    def __init__(self, organizations_client=None):
        """Initialize with optional Organizations client."""
        self.organizations_client = organizations_client or boto3.client('organizations')
    
    def process_policies(self, principal_policies, module=None):
        """Process policies with allow ('a') and deny ('d') types, applying deny precedence.
        
        Args:
            principal_policies: List of policy dictionaries
            module: Optional module name to filter policies by
            
        Returns:
            OrderedDict with account IDs as keys and policy dictionaries as values
        """
        # Filter policies by module if specified
        if module:
            principal_policies = [p for p in principal_policies if p['module'] == module]
        
        # Filter policies by type
        allow_policies = [p for p in principal_policies if p['policy_type'] == 'a']
        deny_policies = [p for p in principal_policies if p['policy_type'] == 'd']
        
        # Process allow policies first
        allow_expanded = self._expand_principals(allow_policies)
        
        # Process deny policies
        deny_expanded = self._expand_principals(deny_policies)
        
        # Remove allow entries that intersect with deny entries
        for account_id in deny_expanded.keys():
            if account_id in allow_expanded:
                del allow_expanded[account_id]
        
        return allow_expanded
    
    def _expand_principals(self, principal_policies):
        """Private method to expand OU principals to individual account principals.
        
        Args:
            principal_policies: List of policy dictionaries
            
        Returns:
            OrderedDict with account IDs as keys and policy dictionaries as values
        """
        expanded_principals = OrderedDict()
        
        for policy in principal_policies:
            if self._is_ou_principal(policy['principal']):
                # Get all accounts under this OU with the policy object
                account_policy_dict = self._get_all_accounts_in_ou(policy['principal'], policy)
                
                # Add the dictionary contents to expanded_principals
                for account_id, original_policy in account_policy_dict.items():
                    expanded_policy = {
                        'principal': account_id,
                        'module': original_policy['module'],
                        'policy_type': original_policy['policy_type'],
                        'regions': original_policy['regions'].copy(),
                        'payload': original_policy['payload']
                    }
                    expanded_principals[account_id] = expanded_policy
            else:
                # Keep non-OU principals as-is
                expanded_principals[policy['principal']] = policy
        
        return expanded_principals
    
    def _is_ou_principal(self, principal):
        """Check if principal represents an OU or root."""
        return principal and (principal.startswith(('r-', 'ou-')) and not re.match(r'^\d+$', principal))
    
    def _get_all_accounts_in_ou(self, ou_id, principal_policy):
        """Recursively get all account IDs under an OU with their associated policy.
        
        Args:
            ou_id: The OU ID to expand
            principal_policy: The policy dictionary associated with this OU
            
        Returns:
            OrderedDict with account IDs as keys and policy dictionaries as values
        """
        accounts = OrderedDict()
        
        try:
            # Get direct account children with pagination
            paginator = self.organizations_client.get_paginator('list_children')
            account_pages = paginator.paginate(
                ParentId=ou_id,
                ChildType='ACCOUNT'
            )
            
            # Add all direct account children
            for page in account_pages:
                for child in page['Children']:
                    accounts[child['Id']] = principal_policy
            
            # Get all child OUs with pagination
            ou_pages = paginator.paginate(
                ParentId=ou_id,
                ChildType='ORGANIZATIONAL_UNIT'
            )
            
            for page in ou_pages:
                for child_ou in page['Children']:
                    # Recursively get accounts from child OUs
                    child_accounts = self._get_all_accounts_in_ou(child_ou['Id'], principal_policy)
                    accounts.update(child_accounts)
                
        except Exception as e:
            print(f"Error retrieving children for OU {ou_id}: {e}")
        
        return accounts


# Test code
account_list = 'budgets,a,r-hkhg,us-east-1\nbudgets,d,521069554442'
try:
    policies = parse_granular_config(account_list)
    client = boto3.client(
        'organizations',
        region_name="us-east-1", #MUST be us-east-1 regardless of region you have the Lambda
    )
    res = OrganizationsPrincipalExpander(client).process_policies(policies, module='budgets')
    print(res)
except Exception as exc:
    print(f"Error trapped: {exc}")