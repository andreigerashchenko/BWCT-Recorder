import os
from pathlib import Path
import stat

def delete_file_safe(file_path):
    """
    ## delete_ext_safe

    Safely deletes files at given path.

    Parameters:
        file_path (string): path to the file
    """
    # try:
    dfile = Path(file_path)
    dfile.unlink(missing_ok=True)
    # except Exception as e:
        # logger.exception(str(e))

def check_WriteAccess(path, is_windows=False, logging=False):
    """
    ## check_WriteAccess

    Checks whether given path directory has Write-Access.

    Parameters:
        path (string): absolute path of directory
        is_windows (boolean): is running on Windows OS?
        logging (bool): enables logging for its operations

    **Returns:** A boolean value, confirming whether Write-Access available, or not?.
    """
    # check if path exists
    dirpath = Path(path)
    # logger.info(
    #     f"directory path to test: {dirpath}"
    # )
    try:
        if not (dirpath.exists() and dirpath.is_dir()):
            # logger.warning(
            #     "Specified directory `{}` doesn't exists or valid.".format(path)
            # )
            print("Specified directory `{}` doesn't exists or valid.".format(path))
            return False
        else:
            path = dirpath.resolve()
    except:
        return False
    # check filepath on *nix systems
    if not is_windows:
        uid = os.geteuid()
        gid = os.getegid()
        s = os.stat(path)
        mode = s[stat.ST_MODE]
        print(
            f"""
            effective UID: {uid}, file ST_UID: {s[stat.ST_UID]}, 
            mode: {mode}, file S_IWUSR: {stat.S_IWUSR}, 

            effective GID: {gid}, file ST_GID: {s[stat.ST_GID]}, 
            mode: {mode}, file S_IWGRP: {stat.S_IWGRP}, 
            
            mode: {mode}, S_IWOTH: {stat.S_IWOTH}"""
        )
        return (
            ((s[stat.ST_UID] == uid) and (mode & stat.S_IWUSR))
            or ((s[stat.ST_GID] == gid) and (mode & stat.S_IWGRP))
            or (mode & stat.S_IWOTH)
        )
    # otherwise, check filepath on windows
    else:
        write_accessible = False
        temp_fname = os.path.join(path, "temp.tmp")
        try:
            fd = os.open(temp_fname, os.O_WRONLY | os.O_CREAT | os.O_TRUNC)
            os.close(fd)
            write_accessible = True
        except Exception as e:
            if isinstance(e, PermissionError):
                # logger.error(
                #     "You don't have adequate access rights to use `{}` directory!".format(
                #         path
                #     )
                # )
                print("You don't have adequate access rights to use `{}` directory!".format(
                        path
                    ))
            # logging and logger.exception(str(e))
        finally:
            delete_file_safe(temp_fname)
        return write_accessible

output = "/media/pi/0123-45671/recordings.mp4"

abs_path = os.path.abspath(output)
test = check_WriteAccess(
    os.path.dirname(abs_path)
)

print(test)