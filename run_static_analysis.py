import argparse
from github import Github
import os

# Input variables from Github action
GITHUB_TOKEN = os.getenv('INPUT_GITHUB_TOKEN')
PR_NUM = int(os.getenv('INPUT_PR_NUM'))
WORK_DIR = os.getenv('GITHUB_WORKSPACE')
REPO_NAME = os.getenv('INPUT_REPO')
SHA = os.getenv('GITHUB_SHA')
COMMENT_TITLE = os.getenv('INPUT_COMMENT_TITLE')
ONLY_PR_CHANGES = os.getenv('INPUT_REPORT_PR_CHANGES_ONLY')

# Max characters per comment - 65536
# Make some room for HTML tags and error message
MAX_CHAR_COUNT_REACHED = '!Maximum character count per GitHub comment has been reached! Not all warnings/errors has been parsed!'
COMMENT_MAX_SIZE = 65000
current_comment_length = 0

def is_part_of_pr_changes(file_path, issue_file_line, files_changed_in_pr):
    if ONLY_PR_CHANGES == "false":
        return True

    file_name = file_path[file_path.rfind('/')+1:]
    print(f"Looking for issue found in file={file_name} ...")
    for file, (status, lines_changed_for_file) in files_changed_in_pr.items():
        print(f"Changed file by this PR {file} with status {status} and changed lines {lines_changed_for_file}")
        if file == file_name:
            if status == "added":
                return True

            for (start, end) in lines_changed_for_file:
                if issue_file_line >= start and issue_file_line <= end:
                    return True

    return False

def get_lines_changed_from_patch(patch):
    lines_changed = []
    lines = patch.split('\n')

    for line in lines:
        # Example line @@ -43,6 +48,8 @@
        # ------------ ^
        if line.startswith("@@"):
            # Example line @@ -43,6 +48,8 @@
            # ----------------------^
            idx_beg = line.index("+")

            # Example line @@ -43,6 +48,8 @@
            #                       ^--^
            idx_end = line[idx_beg:].index(",")
            line_begin = int(line[idx_beg + 1 : idx_beg + idx_end])

            idx_beg = idx_beg + idx_end
            idx_end = line[idx_beg + 1 : ].index("@@")

            num_lines = int(line[idx_beg + 1 : idx_beg + idx_end])

            lines_changed.append((line_begin, line_begin + num_lines))

    return lines_changed

def setup_changed_files():
    files_changed = dict()

    g = Github(GITHUB_TOKEN)
    repo = g.get_repo(REPO_NAME)
    pull_request = repo.get_pull(PR_NUM)
    num_changed_files = pull_request.changed_files
    print(f"Changed files {num_changed_files}")
    files = pull_request.get_files()
    for file in files:
        # additions # blob_url # changes # contents_url # deletions # filename
        # patch # previous_filename # raw_url # sha # status
        # print(f"File: additions={file.additions} blob_url={file.blob_url} changes={file.changes} contents_url={file.contents_url}"\
        #     f"deletions={file.deletions} filename={file.filename} patch={file.patch} previous_filename={file.previous_filename}"\
        #     f"raw_url={file.raw_url} sha={file.sha} status={file.status} ")

        if file.patch is not None:
            lines_changed_for_file = get_lines_changed_from_patch(file.patch)
            files_changed[file.filename] = (file.status, lines_changed_for_file)

    return files_changed

def check_for_char_limit(incoming_line):
    global current_comment_length
    return (current_comment_length + len(incoming_line)) <= COMMENT_MAX_SIZE

def get_file_line_end(file, file_line_start):
    try:
        with open(WORK_DIR + "/" + file) as result_file:
            num_lines = len(result_file.readlines())
            return min(file_line_start + 5, num_lines)
    except:
        return file_line_start + 5

def create_comment_for_output(tool_output, prefix, files_changed_in_pr, category):
    issues_found = 0
    global current_comment_length
    output_string = ''
    for line in tool_output:
        if category in line:
            line = line.replace(prefix, "")
            file_path_end_idx = line.index(':')
            file_path = line[:file_path_end_idx]
            line = line[file_path_end_idx+1:]
            file_line_start = int(line[:line.index(':')])
            file_line_end = get_file_line_end(file_path, file_line_start)
            description = f"\n```diff\n!Line: {file_line_start} - {line[line.index(' ')+1:]}``` \n"

            new_line = f'\n\nhttps://github.com/{REPO_NAME}/blob/{SHA}/{file_path}#L{file_line_start}-L{file_line_end} {description} <br>\n'

            if is_part_of_pr_changes(file_path, file_line_start, files_changed_in_pr):
                if check_for_char_limit(new_line):
                    output_string += new_line
                    current_comment_length += len(new_line)
                    issues_found += 1
                else:
                    current_comment_length = COMMENT_MAX_SIZE
                    return output_string, issues_found

    return output_string, issues_found

def read_files_and_parse_results(files_changed_in_pr, category):
    # Get cppcheck and clang-tidy files
    parser = argparse.ArgumentParser()
    parser.add_argument('-cc', '--cppcheck', help='Output file name for cppcheck', required=True)
    parser.add_argument('-ct', '--clangtidy', help='Output file name for clang-tidy', required=True)
    cppcheck_file_name = parser.parse_args().cppcheck
    clangtidy_file_name = parser.parse_args().clangtidy

    cppcheck_content = ''
    with open(cppcheck_file_name, 'r') as file:
        cppcheck_content = file.readlines()

    clang_tidy_content = ''
    with open(clangtidy_file_name, 'r') as file:
        clang_tidy_content = file.readlines()

    line_prefix = f'{WORK_DIR}'

    cppcheck_comment, cppcheck_issues_found = create_comment_for_output(cppcheck_content, line_prefix, files_changed_in_pr, category)
    clang_tidy_comment, clang_tidy_issues_found = create_comment_for_output(clang_tidy_content, line_prefix, files_changed_in_pr, category)

    return cppcheck_comment, clang_tidy_comment, cppcheck_issues_found, clang_tidy_issues_found

def prepare_comment_body(cppcheck_comment, clang_tidy_comment, cppcheck_issues_found, clang_tidy_issues_found, category):
    
    category_header_map = {
        "error:": "error",
        "warning:": "warning",
        "portability:": "portability issue",
        "performance:": "performance issue",
        "style:": "style issue",
        "information:": "information issue"
    }

    category_text = "issues"
    if category in category_header_map:
        if cppcheck_issues_found > 1:
            category_text = category_header_map[category] + "s" # plural
        else:
            category_text = category_header_map[category]

    if cppcheck_issues_found == 0 and clang_tidy_issues_found == 0:
        full_comment_body = f'## <p align="center"><b> :white_check_mark: {COMMENT_TITLE} - no issues found! :white_check_mark: </b></p>'
    else:
        full_comment_body = f'## <p align="center"><b> :zap: {COMMENT_TITLE} :zap: </b></p> \n\n'

        if len(cppcheck_comment) > 0:
            full_comment_body +=f'<details> <summary> <b> :red_circle: Cppcheck found'\
            f' {cppcheck_issues_found} {category_text}! Click here to see details. </b> </summary> <br>'\
            f'{cppcheck_comment} </details>'

        full_comment_body += "\n\n *** \n"

        if len(clang_tidy_comment) > 0:
            full_comment_body += f'<details> <summary> <b> :red_circle: clang-tidy found'\
            f' {clang_tidy_issues_found} {"issues" if clang_tidy_issues_found > 1 else "issue"}! Click here to see details. </b> </summary> <br>'\
            f'{clang_tidy_comment} </details><br>\n'

    if current_comment_length == COMMENT_MAX_SIZE:
        full_comment_body += f'\n```diff\n{MAX_CHAR_COUNT_REACHED}\n```'

    print(f'Repo={REPO_NAME} pr_num={PR_NUM} comment_title={COMMENT_TITLE}')

    return full_comment_body

def create_or_edit_comment(comment_body):
    g = Github(GITHUB_TOKEN)
    repo = g.get_repo(REPO_NAME)
    pr = repo.get_pull(PR_NUM)

    # Create a new comment
    pr.create_issue_comment(body = comment_body)

if __name__ == "__main__":
    files_changed_in_pr = setup_changed_files()
    
    categories = ["error:", "warning:", "portability", "performance:", "style:", "information:"]
    
    num_cppcheck_issues_found_in_each_category = []
    comment_body_in_each_category = []
    
    for category in categories:
        cppcheck_comment, clang_tidy_comment, cppcheck_issues_found, clang_tidy_issues_found = read_files_and_parse_results(files_changed_in_pr, category)
        comment_body = prepare_comment_body(cppcheck_comment, clang_tidy_comment, cppcheck_issues_found, clang_tidy_issues_found, category)
        num_cppcheck_issues_found_in_each_category.append(cppcheck_issues_found)
        comment_body_in_each_category.append(comment_body)
        
    if all(v == 0 for v in num_cppcheck_issues_found_in_each_category):
        # No issues in any category
        create_or_edit_comment(comment_body_in_each_category[0])
    else:
        for i in range(len(categories)):
            comment_body = comment_body_in_each_category[i]
            if num_cppcheck_issues_found_in_each_category[i] > 0:
                create_or_edit_comment(comment_body)
