import os
import sys
import git

repo = git.Repo('.')

print(repo.git.execute('git checkout main'.split()))
print(repo.git.execute('git pull'.split()))


with open("data-collection/utils/_version.py") as f:
    old_ver = f.read().split('v')[-1].replace("'", '')


bump='patch'
if len(sys.argv)>1:
	bump = sys.argv[1]

maj, minor, patch = map(int, old_ver.split('.'))

if bump=='patch':
	new_ver = '.'.join(map(str,[maj, minor, patch + 1]))
elif bump=='minor':
	new_ver = '.'.join(map(str,[maj, minor + 1, 0]))
else:
	raise NotImplementedError('only patch and minor are implemented')

print(repo.git.execute(f"git checkout -b 'release/{new_ver}'".split()))


tx = open('data-collection/utils/_version.py').read()
with open('data-collection/utils/_version.py', "w") as f:
	f.write(tx.replace({old_ver},{new_ver}))


filenames = [
    'data-collection/deploy/deploy-data-read-permissions.yaml',
    'data-collection/deploy/deploy-data-collection.yaml',
    'data-collection/deploy/deploy-in-management-account.yaml',
    'data-collection/deploy/deploy-in-linked-account.yaml',
]
for filename in filenames:
	tx = open(filename).read()
	with open(filename, "w") as f:
		f.write(tx.replace(f"{old_ver}", f"{new_ver}"))


print(repo.git.execute('git diff HEAD --unified=0'.split()))

print('to undo:\n git checkout HEAD -- cfn-templates/cid-cfn.yml cid/_version.py')
print(f"to continue:\n git commit -am 'release {new_ver}'; git push origin 'release/{new_ver}'")
